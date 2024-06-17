"""Controller interface for ws_2811 light strip with spidev library.

Includes server client implementations.
"""
import os
import numpy as np
import threading
import time
import spidev
import zmq

# LED strip configuration:
LED_COUNT = 14  # Number of LED pixels.
SPI_BUS = 0  # SPI bus (default is 0)
SPI_DEVICE = 0  # SPI device (default is 0)
SPI_MAX_SPEED_HZ = 8000000  # Maximum speed for SPI in Hz
LED_BRIGHTNESS = 100


class Color:
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b


class PixelStrip:
    def __init__(
        self, LED_COUNT=0, LED_FREQ_HZ=0, LED_BUS=0, LED_DEVICE=0, LED_BRIGHTNESS=255
    ):
        self.strip = spidev.SpiDev()
        self.strip.open(LED_BUS, LED_DEVICE)
        self.strip.max_speed_hz = LED_FREQ_HZ

        self.LED_COUNT = LED_COUNT
        self.led_colors = [Color(0, 0, 0)] * self.LED_COUNT

        self.Brightness = LED_BRIGHTNESS

    def setBrightness(self, Brightness: np.uint8):
        if 0 <= Brightness < 256:
            self.Brightness = Brightness

    def setPixelColor(self, n: int, color: Color):
        if 0 <= n < self.LED_COUNT:
            self.led_colors[n] = color

    def rgb_to_spi_data(self, r, g, b):
        r, g, b = int(r), int(g), int(b)
        data = []
        for color in [g, r, b]:  # WS2812 expects GRB order
            for i in range(8):
                if color & (1 << (7 - i)):
                    data.append(0b11111000)  # 1 bit
                else:
                    data.append(0b11000000)  # 0 bit
        return data

    def show(self):
        k = self.Brightness / 255
        data = [
            self.rgb_to_spi_data(color.r * k, color.g * k, color.b * k)
            for color in self.led_colors
        ]
        # flatten the list
        data = sum(data, [])
        self.strip.xfer2(data)

    def numPixels(self):
        return self.LED_COUNT


class LightStripController:
    def __init__(self, dt=0.005):
        self.strip = PixelStrip(
            LED_COUNT,
            SPI_MAX_SPEED_HZ,
            SPI_BUS,
            SPI_DEVICE,
            LED_BRIGHTNESS,
        )

        self.dt = dt
        self.t = 0

        self.mode = "walk"
        self.pulse_pattern = "NULL"
        self.pattern_interval = 2.0
        self.base_color = Color(0, 0, 0)
        self.do_pulse = False

        n_pixels = self.strip.numPixels()
        self.rand_pixels = int(0.5 * n_pixels)
        self.random_lights = np.random.choice(n_pixels, self.rand_pixels, replace=False)

        # start a run thread
        self.running = True
        self.run_thread = threading.Thread(target=self.run)
        self.run_thread.start()

        self.set_mode("breathe", 60, [255, 160, 8])

    def set_mode(self, mode_string, tempo, base_color):
        # Implement light strip specific control
        self.mode = mode_string
        self.pattern_interval = 60 / tempo
        self.t = 0
        self.base_color = Color(*base_color)
        self.start_color = np.array(
            [self.base_color.r, self.base_color.g, self.base_color.b]
        )
        random_offset = np.random.randint(-20, 21, size=3)
        self.end_color = np.clip(self.start_color + random_offset, 0, 255)
        print(self.start_color, self.end_color)

        print(
            f"Light strip mode set to {mode_string} with tempo {tempo} and base color {base_color}"
        )

    def set_next_beat_time(self, next_beat_time):
        # Implement light strip specific control
        print(f"Next beat time set to {next_beat_time}")

    def update(self):
        if self.mode == "breathe":
            self.breathe()
        elif self.mode == "water":
            self.water()
        elif self.mode == "sparkling":
            self.sparkling()
        else:
            pass
            # print(f"Invalid mode for {self.__class__.__name__}")

    def send_pulse(self, pulse_pattern_string, strength, duration):
        self.do_pulse = True
        # TOFIX
        self.pulse_strength = 255
        self.pulse_duration = duration

    def pulse(self, strength, duration):
        # turn off then turn on for several times
        for turn in range(1, 5):
            print(f"pulse: {turn} {strength}")
            # turnoff
            self.strip.setBrightness(0)
            self.strip.show()

            self.strip.setBrightness(strength)
            for i in reversed(range(self.strip.numPixels())):
                self.strip.setPixelColor(i, self.base_color)
                self.strip.show()
                time.sleep(duration / self.strip.numPixels() / 4)

        # turnoff
        self.strip.setBrightness(0)
        self.strip.show()

        self.strip.setBrightness(LED_BRIGHTNESS)

    def run(self):
        while self.running:
            st = time.time()
            if self.do_pulse:
                self.pulse(self.pulse_strength, self.pulse_duration)
                self.do_pulse = False
            else:
                self.update()
            end = time.time()
            sleep_time = max(0, self.dt - (end - st))
            self.t += (end - st) + sleep_time
            self.t %= self.pattern_interval
            time.sleep(sleep_time)

    def breathe(self):
        # in this mode the light will
        # oscillate brightness according to a cosine function 1/2 (1 + a cos(t * 2 pi))
        # and the color will be the base color

        a = 0.7
        # a should be [0.4, 1.0] to be effective
        brightness = (
            LED_BRIGHTNESS
            * (1 + a * np.cos(self.t * 2 * np.pi / self.pattern_interval))
            / 2
        )
        self.strip.setBrightness(np.clip(brightness, 0, 255))
        num_pixels = self.strip.numPixels()
        indices = np.arange(num_pixels)

        # Compute the gradient colors using linear interpolation
        half_num_pixels = num_pixels // 2
        first_half = np.outer(
            1 - indices[:half_num_pixels], self.start_color
        ) + np.outer(indices[:half_num_pixels], self.end_color)
        second_half = np.outer(
            1 - indices[half_num_pixels:], self.end_color
        ) + np.outer(indices[half_num_pixels:], self.start_color)

        color = np.vstack((first_half, second_half))

        # shift by num_pixels * (self.t / self.pattern_interval)
        shift = int(num_pixels * (self.t / self.pattern_interval)) % num_pixels
        color = np.roll(color, shift, axis=0)
        # Set the pixel colors
        for i in range(num_pixels):
            self.strip.setPixelColor(i, Color(*color[i]))
        self.strip.show()

    def water(self):
        # in this mode the light will
        # turn on from the bottom to the top
        # in [0, 0.5] will light up the t / 0.5 part of the strip
        # in [0.5, 1] will turn off the strip from the bottom to top
        t = self.t / self.pattern_interval
        phase = t > 0.5
        n_led = self.strip.numPixels() * (t if not phase else t - 0.5) * 2
        if phase == 0:
            for i in range(self.strip.numPixels()):
                if i < n_led:
                    self.strip.setPixelColor(i, self.base_color)
                else:
                    self.strip.setPixelColor(i, Color(0, 0, 0))
        else:
            for i in range(self.strip.numPixels()):
                if i < n_led:
                    self.strip.setPixelColor(i, Color(0, 0, 0))
                else:
                    self.strip.setPixelColor(i, self.base_color)
        self.strip.show()

    def sparkling(self):
        # in this mode the light will
        # randomly turn on and off
        if int(self.t / self.pattern_interval * 10) != int(
            (self.t - self.dt) / self.pattern_interval * 10
        ):
            self.random_lights = np.random.choice(
                self.strip.numPixels(), self.rand_pixels, replace=False
            )
        for i in range(self.strip.numPixels()):
            if i in self.random_lights:
                self.strip.setPixelColor(i, self.base_color)
            else:
                self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()

    def stop(self):
        self.running = False
        self.run_thread.join()
        print("Light strip run thread stopped.")
        self.strip.setBrightness(0)
        self.strip.show()
        print("Light strip turned off.")


class LEDController:
    # For debugging on the laptop
    def __init__(self, led_name):
        self.led_path = f"/sys/class/leds/{led_name}/brightness"
        self.set_brightness(0)

    def set_brightness(self, brightness):
        # Ensure we have the rights to modify the file
        os.system(f'sudo bash -c "echo {brightness} > {self.led_path}"')

    def send_pulse(self, pulse_pattern_string, strength, duration):
        self.set_brightness(1)
        time.sleep(duration)
        self.set_brightness(0)

    def blink(self, duration, interval=0.5):
        end_time = time.time() + duration
        while time.time() < end_time:
            self.set_brightness(1)  # Turn on the LED
            time.sleep(interval)
            self.set_brightness(0)  # Turn off the LED
            time.sleep(interval)


class LightControllerServer:
    def __init__(
        self,
        light_controller1: LightStripController,
    ):
        self.light_controller1 = light_controller1

        # Set up ZMQ context and socket
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind("tcp://*:5555")

    def run(self):
        print("Light Controller Server started. Waiting for requests...")
        while True:
            message = self.socket.recv_pyobj()
            print(f"Received message: {message}")

            if message["type"] == "set_mode":
                self.handle_set_mode(
                    message["mode"],
                    message["tempo"],
                    message["base_color"],
                )
            elif message["type"] == "send_pulse":
                self.handle_send_pulse(
                    message["pulse_pattern"],
                    message["strength"],
                    message["duration"],
                )
            elif message["type"] == "stop":
                self.handle_stop()
            else:
                print("Unknown message type.")

            self.socket.send_pyobj("OK")

            if message["type"] == "stop":
                break

    def handle_set_mode(self, mode, tempo, base_color):
        self.light_controller1.set_mode(mode, tempo, base_color)

    def handle_send_pulse(self, pulse_pattern, strength, duration):
        self.light_controller1.send_pulse(pulse_pattern, strength, duration)

    def handle_stop(self):
        self.light_controller1.stop()


class LightControllerClient:
    def __init__(self):
        # Set up ZMQ context and socket
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect("tcp://localhost:5555")

    def set_mode(self, mode, tempo, base_color):
        message = {
            "type": "set_mode",
            "mode": mode,
            "tempo": tempo,
            "base_color": base_color,
        }
        self.socket.send_pyobj(message)
        response = self.socket.recv_pyobj()
        # print(f"Response from server: {response}")

    def send_pulse(self, pulse_pattern, strength, duration):
        message = {
            "type": "send_pulse",
            "pulse_pattern": pulse_pattern,
            "strength": strength,
            "duration": duration,
        }
        self.socket.send_pyobj(message)
        response = self.socket.recv_pyobj()
        # print(f"Response from server: {response}")

    def stop(self):
        message = {"type": "stop"}
        self.socket.send_pyobj(message)
        response = self.socket.recv_pyobj()
        # print(f"Response from server: {response}")


if __name__ == "__main__":
    # try:
    #     light_controller = LightStripController()
    #     light_controller_server = LightControllerServer(light_controller)
    #     light_controller_server.run()
    # except KeyboardInterrupt:
    #     pass

    light_controller = LightStripController()
    light_controller_server = LightControllerServer(light_controller)
    import threading

    server_thread = threading.Thread(target=light_controller_server.run)
    server_thread.start()

    # try:
    #     light_controller_client = LightControllerClient()
    #     light_controller_client.set_mode("breathe", 60, [255, 255, 0])
    #     time.sleep(20)
    #     for i in range(5):
    #         light_controller_client.send_pulse("", 10, 1)
    #         time.sleep(2)
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     light_controller_client.stop()

    server_thread.join()
