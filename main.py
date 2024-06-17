import numpy as np
import time
from pa_monitor import AudioMonitor
from music_analyser import MusicAnalyser
from controller import FerroControllerClient, LightControllerClient, LEDController

from config import *


# from controller.light_controller import LED_PIN1, LED_PIN2, LED_CHANNEL1, LED_CHANNEL2

# use hop length = 512
# get data interval should be about 0.010s


class MainController:
    def __init__(self, audio_source):
        print("initializing ferro controller...")
        self.ferro_fluid_controller = FerroControllerClient()
        print("initializing light controller...")
        self.light_strip_controller = LightControllerClient()

        mode = self.generate_ferrofluid_mode(120)
        self.ferro_fluid_controller.set_mode(mode, 120)
        mode, color = self.generate_light_mode_and_color(120)
        self.light_strip_controller.set_mode("water", 60, color)

        # self.led_controller = LEDController("tpacpi::power")

        print("initializing audio monitor...")
        self.audio_monitor = AudioMonitor(audio_source, delay_seconds=delay_seconds)
        print("initializing music analyzer...")
        self.audio_analyzer = MusicAnalyser(
            sr=sr,
            history_s=history_s,
            hop_length=hop_length,
            frame_length=frame_length,
            delay_seconds=delay_seconds,
        )

    def generate_light_mode_and_color(self, tempo):
        mode = np.random.choice(["water", "breathe", "sparkling"], p=[0.5, 0.3, 0.2])
        color = colors_dict[np.random.choice(list(colors_dict.keys()))]
        print("random sampled", color, mode)
        return mode, color

    def generate_ferrofluid_mode(self, tempo):
        return "walk"

    def run(self):
        print("starting monitor")
        self.audio_monitor.run()
        hop_length = hop_length * hops_per_analyse
        time_interval = hop_length / sr
        try:
            while True:
                st = time.time()
                frame = self.audio_monitor.get_data(hop_length)
                if not len(frame):
                    continue
                print(
                    f"Get data of length {len(frame)}, queue length {self.audio_monitor.queue_length()}"
                )
                frame = frame[::2]
                assert (
                    len(frame) == hop_length
                ), f"Frame length {len(frame)} != {hop_length}"
                analyse_results = self.audio_analyzer.analyze(frame)
                if analyse_results["send_pulse"]:
                    self.light_strip_controller.send_pulse(
                        "beat", analyse_results["strength"], 0.1
                    )
                    # self.ferrofluid_controller.send_pulse(
                    #     "beat", analyse_results["strength"], 0.1
                    # )
                if analyse_results["set_mode"]:
                    tempo = analyse_results["tempo"]
                    # set mode and color for lightstrip
                    mode_light, color = self.generate_light_mode_and_color(tempo)
                    self.light_strip_controller.set_mode(mode_light, tempo, color)

                    # set mode for ferrofluid
                    # mode_fluid = self.generate_ferrofluid_mode(tempo)
                    # self.ferro_fluid_controller.set_mode(mode_fluid, tempo)

                # if analyse_results["next_beat_time"]:
                #     next_beat_time = analyse_results["next_beat_time"]
                #     self.ferrofluid_controller.set_next_beat_time(next_beat_time)
                time.sleep(max(time_interval - (time.time() - st), 0) * 0.5)
                last_get_time = st
        except KeyboardInterrupt:
            pass
        finally:
            self.audio_monitor.stop()
            self.light_strip_controller.stop()
            self.ferro_fluid_controller.stop()
            print("Stopped monitoring")


if __name__ == "__main__":
    controller = MainController(
        "alsa_output.platform-bcm2835_audio.stereo-fallback.monitor"
    )
    controller.run()
