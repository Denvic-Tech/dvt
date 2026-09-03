def parse_kafka_config_response(response):
    """
    Парсер DescribeConfigsResponse_v2 для kafka-python.
    Возвращает dict: {config_name: config_value}
    """

    resp = response[0]
    resources = resp.resources
    if not resources:
        raise RuntimeError("No resources in describe_configs response")

    resource = resources[0]

    config_entries = resource[4]
    configs = {}

    for entry in config_entries:
        name = entry[0]
        value = entry[1]
        configs[name] = value

    return configs
