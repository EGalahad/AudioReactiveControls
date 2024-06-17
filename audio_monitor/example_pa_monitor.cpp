#include "src/pa_monitor.hpp"
#include <thread>
#include <chrono>

// consumer thread
void consumer(PulseAudioMonitor &monitor) {
    std::vector<int16_t> data;
    auto start = std::chrono::high_resolution_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));

        monitor.get_data(0.001, data);
        std::cout << "Data size: " << data.size() << std::endl;

        auto end = std::chrono::high_resolution_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(end - start)
                .count() > 10) {
            break;
        }
    }

    // dump data to a file
    std::cout << "Dumping data to file..." << std::endl;
    // print data dtype, data length
    std::cout << "Data dtype: int16_t" << std::endl;
    std::cout << "Data length: " << data.size() << std::endl;
    std::ofstream file("data.raw", std::ios::binary);
    file.write(reinterpret_cast<const char *>(data.data()),
               data.size() * sizeof(DataType));
}

int main() {
    PulseAudioMonitor monitor(
        std::string("bluez_sink.F8_20_A9_33_0B_6A.a2dp_sink.monitor"));
    monitor.run();
    consumer(monitor);
    monitor.stop();
    return 0;
}
