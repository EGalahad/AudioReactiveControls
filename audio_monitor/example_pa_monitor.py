import pa_monitor
import time
import numpy as np
import wave


monitor = pa_monitor.AudioMonitor("alsa_output.platform-bcm2835_audio.stereo-fallback.monitor", delay_seconds=0.1)
st = time.time()


hop_length = 512
interval = hop_length / 44100
all = []
monitor.run()
time.sleep(1)
while time.time() - st < 10:
    data = monitor.get_data(hop_length)
    # time.sleep(interval * 0.9)
    if len(data):
        all.append(data)
monitor.stop()

# concat all data and save to a wav file
all_data = np.concatenate(all)
print(all_data.shape)
# breakpoint()

time.sleep(1)
print("Saving to output.wav!")

with wave.open("output.wav", "wb") as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(44100)
    wf.writeframes(all_data.tobytes())
