import librosa
import numpy as np

import time
import pickle

# import line_profiler

# each time, the manager will get 0.01s audio data and send to the analyzer
# the analyzer will cache the most recent 5s (to be determined) audio data

# the analyzer will
# 1. determine if the song changes beat or there is a new song playing. it will use librosa to get the tempo of the audio data. and generate a color pattern for the light strip.
# 2. determine if there is a beat in the most recent 0.01s frame


class MusicAnalyser:
    def __init__(
        self,
        sr=44100,
        history_s=0.5,
        hop_length=512,
        frame_length=2048,
        delay_seconds=0.2,
        **kwargs
    ):
        self.sr = sr
        # buffer last 5s audio data
        self.history_len = history_len = int(sr * history_s)
        self.buffer = np.zeros(history_len * 4, dtype=np.int16)
        self.t = history_len

        self.count = 0
        

        self.hop_length = hop_length
        self.frame_length = frame_length
        self.kwargs = kwargs
        kwargs.setdefault("pre_max", 0.03 * sr // hop_length)  # 30ms
        kwargs.setdefault("post_max", 0.00 * sr // hop_length + 1)  # 0ms
        kwargs.setdefault("pre_avg", 0.10 * sr // hop_length)  # 100ms
        kwargs.setdefault("post_avg", 0.10 * sr // hop_length + 1)  # 100ms
        kwargs.setdefault("wait", 0.03 * sr // hop_length)  # 30ms
        kwargs.setdefault("delta", 0.5)

        self.delay_frames = int(sr * delay_seconds / hop_length)
        self.delay_s = self.delay_frames * hop_length / sr

        self.last_tempo = 120
        self.tempo = 120
        self.detected_tempo_change_last_time = False
        self.tempo_change_threshold = 10

        y = np.zeros(history_len, dtype=np.float32)
        S = librosa.feature.melspectrogram(
            y=y,
            sr=self.sr,
            n_fft=self.frame_length,
            hop_length=self.hop_length,
            n_mels=128,
            fmax=0.5 * self.sr,
        )

    def store_frame(self, frame):
        frame_len = len(frame)
        if self.t + frame_len > len(self.buffer):
            self.buffer[: self.history_len] = self.buffer[
                self.t - self.history_len : self.t
            ].copy()
            self.t = self.history_len
        self.buffer[self.t : self.t + frame_len] = frame
        self.t += frame_len

    # @line_profiler.profile
    def analyze(self, frame):
        st = time.time()
        self.store_frame(frame)
        y = self.buffer[self.t - self.history_len: self.t].astype(np.float32) / np.iinfo(np.int16).max
        # print("get y from buffer: ", time.time() - st)
        
        # compute mel spectrogram
        st = time.time()
        S = librosa.stft(
            y=y,
            n_fft=self.frame_length,
            hop_length=self.hop_length,
        )
        print("compute stft: ", time.time() - st)
        S = librosa.core.power_to_db(np.abs(S))
        # compute onset strength
        onset_env = librosa.onset.onset_strength(
            S=S, sr=self.sr, hop_length=self.hop_length
        )
        # normalize onset strength
        onset_env = onset_env - np.min(onset_env)
        onset_env /= np.max(onset_env) + librosa.util.tiny(onset_env)

        onsets_detected = librosa.util.peak_pick(onset_env, **self.kwargs)
        
        st = time.time()
        frames_to_check = [len(onset_env) - self.delay_frames + i for i in range(len(frame) // self.hop_length)]
        frames_to_check = [frame_to_check for frame_to_check in frames_to_check if frame_to_check < len(onset_env)]
        send_pulse = any(frame_to_check in onsets_detected for frame_to_check in frames_to_check)
        # pulse_strength = max(onset_env[frames_to_check])
        # print("check pulse: ", time.time() - st)
        # print(self.t, len(onset_env), send_pulse, onsets_detected[-5:], frames_to_check[-1])

        # # save [y, onset_env, onsets_detected, frame_to_check, send_pulse, pulse_strength]
        # st = time.time()
        # with open("data.pkl", "wb") as f:
        #     pickle.dump([y, self.sr, onset_env, onsets_detected, frames_to_check, send_pulse, pulse_strength], f)
        # print("end saving", time.time() - st)
        
        set_mode = False
        next_beat_time = None
        # if self.t % self.history_len == 0:
        #     tempo, beats = librosa.beat.beat_track(y=y, sr=self.sr)
        #     # if tempo changes and is stable for 2 frames
        #     if abs(tempo - self.last_tempo) > self.tempo_change_threshold:
        #         if abs(tempo - self.tempo) <= self.tempo_change_threshold:
        #             set_mode = True
        #     self.last_tempo, self.tempo = self.tempo, tempo
        #     # compute the time of the next beat, relative to the check frame
        #     if beats[-1] >= frame_to_check:
        #         next_beat_time = librosa.frames_to_time(
        #             [beats[beats > frame_to_check][0] - frame_to_check],
        #             sr=self.sr,
        #             hop_length=self.hop_length,
        #         )[0]
        #     else:
        #         # use tempo to predict the next beat
        #         next_beat_time = -librosa.frames_to_time(
        #             [frame_to_check - beats[-1]], sr=self.sr, hop_length=self.hop_length
        #         )[0]
        #         next_beat_time += np.ceil(-next_beat_time / (60 / tempo)) * (60 / tempo)
        if self.t % self.history_len != (self.t - len(frame)) % self.history_len:
            self.count += 1
            if self.count == 100:
                self.count = 0
                set_mode = True

        return dict(
            send_pulse=send_pulse,
            strength=255,
            set_mode=set_mode,
            tempo=self.tempo,
            next_beat_time=next_beat_time,
        )
