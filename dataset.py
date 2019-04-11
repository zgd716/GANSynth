import tensorflow as tf
import numpy as np
import functools
import pathlib
import json
import os
import spectral_ops
from utils import Struct
from tensorflow.contrib.framework.python.ops import audio_ops


def nsynth_input_fn(filenames, batch_size, num_epochs, shuffle,
                    buffer_size=None, pitches=None, sources=None):

    index_table = tf.contrib.lookup.index_table_from_tensor(sorted(pitches), dtype=tf.int32)

    def parse_example(example):

        features = Struct(tf.parse_single_example(
            serialized=example,
            features=dict(
                path=tf.FixedLenFeature([], dtype=tf.string),
                pitch=tf.FixedLenFeature([], dtype=tf.int64),
                source=tf.FixedLenFeature([], dtype=tf.int64)
            )
        ))

        waveform = tf.read_file(features.path)
        # decode a 16-bit PCM WAV file
        waveform, _ = audio_ops.decode_wav(
            contents=waveform,
            desired_channels=1,
            desired_samples=64000
        )
        waveform = tf.squeeze(waveform)

        label = index_table.lookup(features.pitch)
        label = tf.one_hot(label, len(pitches))

        pitch = tf.cast(features.pitch, tf.int32)
        source = tf.cast(features.source, tf.int32)

        return waveform, label, pitch, source

    dataset = tf.data.TFRecordDataset(filenames)
    if shuffle:
        dataset = dataset.shuffle(buffer_size or sum([
            len(list(tf.io.tf_record_iterator(filename)))
            for filename in filenames
        ]), reshuffle_each_iteration=True)
    dataset = dataset.repeat(num_epochs)
    dataset = dataset.map(parse_example, num_parallel_calls=os.cpu_count())
    # filter just acoustic instruments and just pitches 24-84 (as in the paper)
    dataset = dataset.filter(lambda waveform, label, pitch, source: functools.reduce(
        tf.logical_and,
        filter(None, [
            tf.greater_equal(pitch, min(pitches)) if pitches else pitches,
            tf.less_equal(pitch, max(pitches)) if pitches else pitches,
            tf.reduce_any(tf.equal(sources, source)) if sources else sources,
        ])
    ))
    dataset = dataset.map(lambda waveform, label, pitch, source: (waveform, label), num_parallel_calls=os.cpu_count())
    dataset = dataset.batch(batch_size, drop_remainder=True)
    dataset = dataset.prefetch(1)

    iterator = dataset.make_initializable_iterator()

    tf.add_to_collection(tf.GraphKeys.SAVEABLE_OBJECTS, tf.data.experimental.make_saveable_from_iterator(iterator))
    tf.add_to_collection(tf.GraphKeys.TABLE_INITIALIZERS, iterator.initializer)

    return iterator.get_next()
