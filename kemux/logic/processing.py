from __future__ import annotations

import dataclasses
import importlib.machinery
import logging
import os

import faust
import faust.types

import kemux.logic.routing
import kemux.data.schemas.input
import kemux.data.schemas.output
import kemux.data.schemas.base
import kemux.data.streams.base
import kemux.data.streams.input
import kemux.data.streams.output

DEFAULT_MODELS_PATH = 'streams'


@dataclasses.dataclass(kw_only=True)
class Processor:
    kafka_address: str
    streams_dir: str
    persistent_data_directory: str
    _app: faust.App = dataclasses.field(init=False)
    _source_topics: dict[str, faust.TopicT] = dataclasses.field(init=False)
    __instance: Processor | None = dataclasses.field(init=False, default=None)
    __logger: logging.Logger = dataclasses.field(init=False, default=logging.getLogger(__name__))
    __router: kemux.logic.routing.Router = dataclasses.field(init=False)
    __agents: dict[str, faust.types.AgentT] = dataclasses.field(init=False, default_factory=dict)

    @classmethod
    def init(cls, kafka_address: str, data_dir: str, streams_dir: str) -> Processor:
        if cls.__instance is None:
            instance: Processor = cls(
                kafka_address=kafka_address,
                streams_dir=streams_dir,
                persistent_data_directory=data_dir,
            )
            instance.__logger.info('Initialized receiver')
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s %(levelname)s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            )
            instance.__logger.info(f'Connecting to Kafka broker: {kafka_address}')
            app = faust.App(
                'splitter_broker',
                broker=kafka_address,
                value_serializer='json',
                datadir=instance.persistent_data_directory,
            )
            input_models, output_models = instance.classify_models()
            instance.__router = kemux.logic.routing.Router(
                app=app,
                inputs=input_models,
                outputs=output_models,
            )
            instance._app = app
            cls.__instance = instance
        return cls.__instance
    
    def classify_models(self) -> tuple[
        dict[str, kemux.data.streams.input.InputStream],
        dict[str, kemux.data.streams.output.OutputStream]
    ]:
        if not os.path.isdir(self.streams_dir):
            raise ValueError(f'Invalid streams directory: {self.streams_dir}')
        present_modules: list[str] = filter(
            lambda module: module.endswith('.py'),
            os.listdir(self.streams_dir),
        )
        output_models: dict[str, kemux.data.streams.output.OutputStream] = {}
        input_models: dict[str, kemux.data.streams.input.InputStream] = {}
        for module in present_modules:
            module_name = module.removesuffix('.py')
            module_path = os.path.join(self.streams_dir, module)
            try:
                module = importlib.machinery.SourceFileLoader(module_name, module_path).load_module()
            except (OSError, ImportError) as cant_import_stream_module:
                self.__logger.error(f'Failed to import stream module: {module_name}', exc_info=cant_import_stream_module)
                continue

            stream_class: kemux.data.streams.base.StreamBase
            schema_class: kemux.data.schemas.base.SchemaBase

            if not (stream_class := getattr(module, 'Stream', None)):
                self.__logger.error(f'Invalid stream module: {module_name}. No Stream class found')
            if not (schema_class := getattr(module, 'Schema', None)):
                self.__logger.error(f'Invalid stream module: {module_name}. No Schema class found')
            stream_class.topic = module_name
            schema_class._find_decorated_fields()

            if issubclass(stream_class, kemux.data.streams.output.OutputStream):
                if not issubclass(schema_class, kemux.data.schemas.output.OutputSchema):
                    self.__logger.error(f'Invalid stream module: {module_name}. Schema class is not an OutputSchema')
                    continue
                stream_class.schema = schema_class
                output_models[module_name] = stream_class
            elif issubclass(stream_class, kemux.data.streams.input.InputStream):
                if not issubclass(schema_class, kemux.data.schemas.input.InputSchema):
                    self.__logger.error(f'Invalid stream module: {module_name}. Schema class is not an InputSchema')
                    continue
                schema_class._construct_record_class()
                stream_class.schema = schema_class
                input_models[module_name] = stream_class
            else:
                self.__logger.error(f'Invalid stream module: {module_name}. Class is neither an Input or Output stream')
        return input_models, output_models

    def start(self) -> None:
        self.__logger.info('Starting receiver')
        for stream in self.__router.inputs.values():
            stream: kemux.data.streams.input.InputStream
            self.__logger.info(f'Starting handler for topic: {stream.topic}')
            input_topics_handler: faust.TopicT = stream._get_handler(self._app)  # pylint: disable=protected-access

            async def _process_input_stream_message(messages: faust.StreamT[kemux.data.schemas.input.InputSchema]) -> None:
                self.__logger.info('Processing messages')
                async for message in messages:
                    self.__logger.info(message.__dict__)
                    self.__router.route(stream, message)

            self.__agents[stream.topic] = self._app.agent(input_topics_handler)(_process_input_stream_message)
        self._app.main()
