import logging

import functools

import lib.splitter.streams.primary
import lib.splitter.streams.secondary


@functools.lru_cache
def get_splitter_output_topics() -> list[str]:
    return [
        topic
        for sublist in [
            [
                output.IO.topic
                for output in stream.Outputs.__dict__.values()
                if isinstance(output, type)
            ]
            for stream in [
                lib.splitter.streams.primary,
                lib.splitter.streams.secondary,
            ]
        ]
        for topic in sublist
    ]
