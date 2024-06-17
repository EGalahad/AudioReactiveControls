import time
import numpy as np
import zmq
import threading
import RPi.GPIO as GPIO

class FerroFluidController:
    def __init__(self, dt=0.01):
        self.pins = {
            'downleft': 26,
            'downright': 16,
            'middle': 19,
            'up': 20,
            'standby': 12
        }

        GPIO.setmode(GPIO.BCM)
        
        # Set up high power pins
        GPIO.setup(self.pins['standby'], GPIO.OUT)
        GPIO.output(self.pins['standby'], GPIO.HIGH)
        
        # Set up PWM pins
        for key in ['middle', 'up', 'downleft', 'downright']:
            GPIO.setup(self.pins[key], GPIO.OUT)
            setattr(self, key, GPIO.PWM(self.pins[key], 500))
            getattr(self, key).start(0)

        self.dt = dt
        self.t = 0
        self.mode = "walk"
        self.pulse_pattern = "NULL"
        self.pattern_interval = 10.0

        self.gather()

        self.random_magnet_idx = 1
        self.target_magnet_idx = 0
        self.default_intensity = 90
        self.pulse_strength = 20

        self.running = True
        self.run_thread = threading.Thread(target=self.run)
        self.run_thread.start()

    def _energyoff(self):
        for key in ['middle', 'up', 'downleft', 'downright']:
            getattr(self, key).ChangeDutyCycle(0)

    def gather(self):
        print("Gathering ferrofluid...")
        self.up.ChangeDutyCycle(70)
        self.downleft.ChangeDutyCycle(70)
        self.downright.ChangeDutyCycle(70)
        self.middle.ChangeDutyCycle(100)
        time.sleep(2)
        print("Ferrofluid gathered.")

    def set_mode(self, mode_string, tempo):
        self.mode = mode_string
        self.pattern_interval = 60 / tempo * 20
        self.t = 0  # reset time index when mode changes
        print("Pattern interval set to", self.pattern_interval, "s.")

    def set_next_beat_time(self, next_beat_time):
        self.next_beat = next_beat_time

    def update(self):
        if self.mode == "walk":
            self.walk()
        else:
            pass

    def walk(self):
        if np.floor(self.t / self.pattern_interval) != np.floor((self.t - self.dt) / self.pattern_interval):
            # self.target_magnet_idx = np.random.choice([0, 1, 2, 3], p=[0.1, 0.3, 0.3, 0.3])
            self.target_magnet_idx = (self.target_magnet_idx + 1) % 4
            self.move_start_time = self.t
            # print(f"Moving to magnet {self.target_magnet_idx}.")

        self.move()

    def move(self):
        move_duration = max(self.pattern_interval, 5.0)
        move_progress = (self.t - self.move_start_time) / move_duration

        self._energyoff()

        if move_progress < 1:
            if move_progress < 0.5:
                # move to middle
                current_magnet = self.get_magnet_by_idx(self.random_magnet_idx)
                target_magnet = self.middle
                # print("move to middle")
            else:
                current_magnet = self.middle
                target_magnet = self.get_magnet_by_idx(self.target_magnet_idx)
                # print(f"move to target {self.target_magnet_idx}")

            current_magnet.ChangeDutyCycle(0)
            # int(self.t * a) % b != 0
            # occupancy ratio: 1 - 1/b, frequency: a/b Hz
            # best freq is about 5Hz
            if int(self.t * 15) % 3 != 0:
                target_magnet.ChangeDutyCycle(100)
        else:
            self.random_magnet_idx = self.target_magnet_idx

    def pulse(self):
        pulse_intensity = self.default_intensity - self.pulse_strength * (1 - np.cos(2 * np.pi * self.t / self.pattern_interval))
        magnet = self.get_magnet_by_idx(self.random_magnet_idx)
        magnet.ChangeDutyCycle(pulse_intensity)

    def send_pulse(self, pulse_pattern_string, strength, duration):
        # TOFIX: next time, mimic the implmentation in light controller, all patterns run in the run thread
        self.pulse_strength = 50
        time.sleep(0.5)
        self.pulse_strength = self.default_intensity

    def get_magnet_by_idx(self, idx):
        if idx == 0:
            return self.middle
        elif idx == 1:
            return self.downleft
        elif idx == 2:
            return self.downright
        elif idx == 3:
            return self.up
        else:
            return None

    def run(self):
        while self.running:
            st = time.time()
            self.update()
            end = time.time()
            sleep_time = max(0, self.dt - (end - st))
            self.t += (end - st) + sleep_time
            self.t %= self.pattern_interval
            time.sleep(sleep_time)

    def stop(self):
        self.running = False
        self.run_thread.join()
        self._energyoff()
        GPIO.cleanup()
        print("FerrofluidController stopped and GPIO cleaned up.")


class FerroControllerServer:
    def __init__(self, fero_controller: FerroFluidController):
        self.fero_controller = fero_controller

        # Set up ZMQ context and socket
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind("tcp://*:5556")

    def run(self):
        print("Ferrofluid Controller Server started. Waiting for requests...")
        while True:
            message = self.socket.recv_pyobj()
            print(f"Received message: {message}")

            if message["type"] == "set_mode":
                self.handle_set_mode(message["mode"], message["tempo"])
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

    def handle_set_mode(self, mode, tempo):
        self.fero_controller.set_mode(mode, tempo)

    def handle_send_pulse(self, pulse_pattern, strength, duration):
        self.fero_controller.send_pulse(pulse_pattern, strength, duration)

    def handle_stop(self):
        self.fero_controller.stop()


class FerroControllerClient:
    def __init__(self):
        # Set up ZMQ context and socket
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect("tcp://localhost:5556")

    def set_mode(self, mode, tempo):
        message = {
            "type": "set_mode",
            "mode": mode,
            "tempo": tempo,
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
    import threading

    controller = FerroFluidController()
    fero_controller_server = FerroControllerServer(controller)
    
    # Start the server in a separate thread
    server_thread = threading.Thread(target=fero_controller_server.run)
    server_thread.start()
    
    # try:
    #     # Create a client and use it to control the ferrofluid
    #     fero_controller_client = FerroControllerClient()
    #     fero_controller_client.set_mode("walk", 120)
    #     time.sleep(50)
        
    #     # Example of sending a pulse
    #     fero_controller_client.send_pulse("some_pattern", 50, 0.5)
    #     time.sleep(5)
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     fero_controller_client.stop()

    server_thread.join()
    controller.stop()

