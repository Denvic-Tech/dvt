"""One KRaft broker per session; security sessions are explicitly selected and sequential."""

import asyncio
import ipaddress
import json
import os
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from kafka.admin import KafkaAdminClient, NewTopic
from testcontainers.kafka import KafkaContainer

KAFKA_IMAGE = "confluentinc/cp-kafka:7.6.0"


def _certificate_material(host):
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DVT Kafka test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), True
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sans = [x509.DNSName("localhost"), x509.DNSName("host.docker.internal")]
    try:
        sans.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        sans.append(x509.DNSName(host))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .sign(ca_key, hashes.SHA256())
    )
    return (
        ca.public_bytes(serialization.Encoding.PEM).decode(),
        cert.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def assert_serial_kafka(request):
    if hasattr(request.config, "workerinput") or os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail("Kafka integration must run with -n 0: session brokers may not multiply")


@contextmanager
def running_kafka(protocol="PLAINTEXT", mechanism=None):
    broker = KafkaContainer(KAFKA_IMAGE, docker_client_kw={"timeout": 300}).with_kraft()
    broker.with_kwargs(mem_limit="1g", nano_cpus=2_000_000_000)
    broker.with_envs(
        KAFKA_HEAP_OPTS="-Xms256m -Xmx512m",
        KAFKA_AUTO_CREATE_TOPICS_ENABLE="false",
        KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR="1",
        KAFKA_TRANSACTION_STATE_LOG_MIN_ISR="1",
        KAFKA_TRANSACTION_STATE_LOG_NUM_PARTITIONS="1",
        KAFKA_NUM_PARTITIONS="3",
    )
    props = {"security_protocol": protocol}
    credentials = {}
    if protocol != "PLAINTEXT":
        broker.security_protocol_map = f"BROKER:PLAINTEXT,PLAINTEXT:{protocol}"
    if "SSL" in protocol:
        ca, certificate, key = _certificate_material(broker.get_container_host_ip())
        broker.with_envs(
            KAFKA_SSL_KEYSTORE_TYPE="PEM",
            KAFKA_SSL_KEYSTORE_CERTIFICATE_CHAIN=certificate.replace("\n", r"\n"),
            KAFKA_SSL_KEYSTORE_KEY=key.replace("\n", r"\n"),
            KAFKA_SSL_TRUSTSTORE_TYPE="PEM",
            KAFKA_SSL_TRUSTSTORE_CERTIFICATES=ca.replace("\n", r"\n"),
            KAFKA_SSL_CLIENT_AUTH="none",
        )
        props["ssl_ca_pem"] = ca
    if protocol.startswith("SASL"):
        password = secrets.token_hex(20)
        login_module = (
            "org.apache.kafka.common.security.plain.PlainLoginModule"
            if mechanism == "PLAIN"
            else "org.apache.kafka.common.security.scram.ScramLoginModule"
        )
        jaas = (
            f'{login_module} required username="dvt" password="{password}"'
            + (f' user_dvt="{password}"' if mechanism == "PLAIN" else "")
            + ";"
        )
        broker.with_env("KAFKA_SASL_ENABLED_MECHANISMS", mechanism)
        broker.with_env(
            "KAFKA_LISTENER_NAME_PLAINTEXT_" + mechanism.replace("-", "___") + "_SASL_JAAS_CONFIG",
            jaas,
        )
        props.update(sasl_mechanism=mechanism, sasl_plain_username="dvt")
        credentials["sasl_plain_password"] = password

    docker = broker.get_docker_client().client
    try:
        docker.images.get(KAFKA_IMAGE)
        cached = True
    except Exception:
        cached = False
    pull_started = monotonic()
    if not cached:
        docker.images.pull(KAFKA_IMAGE)
    pull_seconds = monotonic() - pull_started
    started = monotonic()
    try:
        broker.start(timeout=120)
        props["bootstrap_servers"] = [broker.get_bootstrap_server()]
        if mechanism and mechanism.startswith("SCRAM"):
            result = broker.exec(
                [
                    "kafka-configs",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--alter",
                    "--add-config",
                    f"{mechanism}=[iterations=4096,password={password}]",
                    "--entity-type",
                    "users",
                    "--entity-name",
                    "dvt",
                ]
            )
            if result.exit_code:
                raise RuntimeError("Test SCRAM provisioning failed")
        from db_connection.connectors.kafka import build_kafka_config

        config = build_kafka_config(props, credentials)
        admin = KafkaAdminClient(**config)
        try:
            admin.list_topics()
        finally:
            admin.close()
        stats = broker.get_wrapped_container().stats(stream=False)["memory_stats"]
        metrics = {
            "image_cached": cached,
            "pull_seconds": round(pull_seconds, 2),
            "ready_seconds": round(monotonic() - started, 2),
            "memory_usage_bytes": stats["usage"],
            "memory_stats": stats.get("stats", {}),
            "memory_limit_bytes": stats["limit"],
            "bootstrap": broker.get_bootstrap_server(),
            "protocol": protocol,
            "mechanism": mechanism,
        }
        print("KAFKA_METRICS " + json.dumps(metrics, sort_keys=True))
        broker.dvt_properties = props
        broker.dvt_secrets = credentials
        broker.dvt_metrics = metrics
        yield broker
    except Exception:
        if broker.get_wrapped_container() is not None:
            stdout, stderr = broker.get_logs()
            log = (stdout + stderr).decode(errors="replace")
            for secret in [
                *credentials.values(),
                props.get("ssl_ca_pem"),
                locals().get("key"),
                locals().get("certificate"),
            ]:
                if secret:
                    log = log.replace(secret, "<redacted>")
            # Never dump broker configuration: only errors needed for startup diagnostics.
            print(
                "\n".join(
                    line
                    for line in log.splitlines()
                    if any(token in line for token in ("ERROR", "Exception", "required", "ensure"))
                )[-4000:]
            )
        raise
    finally:
        if broker.get_wrapped_container() is not None:
            broker.stop()


@pytest.fixture(scope="session")
def kafka_security_container(request):
    assert_serial_kafka(request)
    protocol, _, mechanism = os.environ.get("DVT_KAFKA_SECURITY", "SSL").partition(":")
    allowed = {"SSL", "SASL_PLAINTEXT", "SASL_SSL"}
    if protocol not in allowed or (
        protocol.startswith("SASL") and mechanism not in {"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"}
    ):
        pytest.fail("Invalid DVT_KAFKA_SECURITY profile")
    with running_kafka(protocol, mechanism or None) as broker:
        yield broker


@pytest.fixture
def kafka_resources(kafka_container):
    from db_connection.connectors.kafka import build_kafka_config

    config = build_kafka_config(kafka_container.dvt_properties, kafka_container.dvt_secrets)
    admin = KafkaAdminClient(**config)
    topics, groups = [], []

    class Resources:
        def topic(self, partitions=3):
            name = "dvt-test-" + uuid4().hex
            admin.create_topics([NewTopic(name, partitions, 1)])
            topics.append(name)
            return name

        def group(self):
            name = "dvt-test-" + uuid4().hex
            groups.append(name)
            return name

        def publish(self, topic, records):
            # kafka-python 2.2.15 producer rejects null header values; aiokafka
            # publishes the real Kafka representation without patching either SDK.
            from aiokafka import AIOKafkaProducer

            async def send():
                producer = AIOKafkaProducer(**config)
                await producer.start()
                try:
                    return [await producer.send_and_wait(topic, **record) for record in records]
                finally:
                    await producer.stop()

            return asyncio.run(send())

        def committed(self, topic, group):
            from kafka import KafkaConsumer, TopicPartition

            consumer = KafkaConsumer(
                **config, group_id=group, enable_auto_commit=False, allow_auto_create_topics=False
            )
            try:
                return {
                    p: consumer.committed(TopicPartition(topic, p))
                    for p in consumer.partitions_for_topic(topic)
                }
            finally:
                consumer.close(autocommit=False)

    try:
        yield Resources()
    finally:
        try:
            if groups:
                admin.delete_consumer_groups(groups)
            if topics:
                admin.delete_topics(topics)
        finally:
            admin.close()
