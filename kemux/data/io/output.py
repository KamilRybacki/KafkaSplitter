import dataclasses

import kemux.data.io.base
import kemux.data.schema.input
import kemux.data.schema.output

import kemux.logic.concurrency


@dataclasses.dataclass
class StreamOutput(kemux.data.io.base.IOBase):
    @staticmethod
    def filter(message: dict) -> bool:
        raise NotImplementedError(f'{__name__}.filter() must be implemented!')

    @classmethod
    async def send(cls, message: dict) -> None:
        transformed_message = cls.schema.transform(message=message)  # type: ignore
        cls.logger.info(f'Sending message: {transformed_message}')
        if cls.schema.validate(message=transformed_message):  # type: ignore
            await cls.topic_handler.send(value=transformed_message)  # type: ignore
        else:
            cls.logger.warning(f'Invalid message: {message}')

    @classmethod
    def declare(cls) -> None:
        kemux.logic.concurrency.try_in_event_loop(
            cls.__declare
        )
        cls.logger.info(f'Output topic declared: {cls.topic}')

    @classmethod
    async def __declare(cls) -> None:
        await cls.topic_handler.declare()
        await cls.topic_handler.send(
            value='__kemux_init__'
        )
