from functools import partial
from types import SimpleNamespace

from celery import Celery
from celery.worker.consumer.consumer import Consumer
from kombu import Exchange, Queue

from services.task_worker import celery_app


def test_refresh_queues_survive_consumer_recreation() -> None:
    queue_names = (
        celery_app.config.CELERY.CELERY_TASKS_QUEUE,
        celery_app.config.CELERY.CELERY_DEPS_QUEUE,
    )
    queues = [
        Queue(name, exchange=Exchange(f"refresh.{index}"), routing_key=f"route.{index}")
        for index, name in enumerate(queue_names)
    ]
    expected = {
        queue.name: (queue.exchange.name, queue.routing_key)
        for queue in queues
    }

    with Celery("extension-refresh-test", broker="memory://", set_as_current=False) as app:
        app.conf.task_queues = [*queues, Queue("unselected.queue")]
        app.amqp.queues.select(queue_names)
        with app.connection_for_read() as connection:
            consumer = SimpleNamespace(app=app, task_consumer=app.amqp.TaskConsumer(connection))
            consumer.add_task_queue = partial(Consumer.add_task_queue, consumer)
            with consumer.task_consumer:
                for queue_name in queue_names:
                    Consumer.cancel_task_queue(consumer, queue_name)
                assert consumer.task_consumer.queues == []

                celery_app._resume_extension_refresh_queues(consumer)

                assert {
                    queue.name: (queue.exchange.name, queue.routing_key)
                    for queue in consumer.task_consumer.queues
                } == expected

            with app.amqp.TaskConsumer(connection) as recreated:
                assert {
                    queue.name: (queue.exchange.name, queue.routing_key)
                    for queue in recreated.queues
                } == expected
