#include <cstddef>
#include <ctime>
#include <deque>
#include <fstream>
#include <iostream>
#include <pulse/pulseaudio.h>
#include <random>
#include <string>
#include <thread>
#include <vector>

/**
 * @brief Given a sink to be monitored, create a virtual sink, to redirect its
 * sink input to, record from the virtual sink and then route back to the
 * original sink with desired delay.
 * @todo use poll based read from the recording stream to implement active
 * control of the delay time.
 * @todo handle destroy the virtual sink and redirect the sink input back to
 * original sink
 * @todo use semaphor variable instead of a chain to initiate the sinks and
 * streams.
 */
#define S16LE
// #define U8

#ifdef S16LE
const auto FORMAT = PA_SAMPLE_S16LE;
using DataType = int16_t;
#endif
#ifdef U8
const auto FORMAT = PA_SAMPLE_U8;
using DataType = uint8_t;
#endif

template <typename T> class FixedDeque {
  private:
    std::deque<T> dq_;
    size_t max_size_;

  public:
    FixedDeque(size_t max_size) : max_size_(max_size) {}

    void push(const T &value) {
        if (dq_.size() == max_size_) {
            dq_.pop_front(); // Remove the oldest element
        }
        dq_.push_back(value); // Add new element
    };

    void insert(typename std::deque<T>::iterator dst, const T *begin,
                const T *end) {
        dq_.insert(dst, begin, end);
    }

    typename std::deque<T>::iterator begin() { return dq_.begin(); }
    typename std::deque<T>::iterator end() { return dq_.end(); }
    void erase(typename std::deque<T>::iterator begin,
               typename std::deque<T>::iterator end) {
        dq_.erase(begin, end);
    }
    size_t size() { return dq_.size(); }
    T &operator[](size_t index) { return dq_[index]; }
};

std::string generateRandomString(size_t length) {
    const char charset[] = "0123456789"
                           "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                           "abcdefghijklmnopqrstuvwxyz";
    const size_t max_index = (sizeof(charset) - 1);

    std::string random_string;
    random_string.reserve(length);

    // Create a random engine and seed it from the system clock
    std::mt19937_64 engine(static_cast<unsigned long>(std::time(nullptr)));
    std::uniform_int_distribution<size_t> distribution(0, max_index - 1);

    for (size_t i = 0; i < length; ++i) {
        random_string += charset[distribution(engine)];
    }

    return random_string;
}

const int RATE = 44100;
const int CHANNELS = 2;

/**
 * @todo support dynamically change the monitored source device when the default
 * source is changed
 */
class PulseAudioMonitor {
  public:
    PulseAudioMonitor(const std::string &monitored_source_name,
                      float delay_seconds = 0.1)
        : monitored_source_name(monitored_source_name),
          delay_bytes(delay_seconds * RATE * CHANNELS * sizeof(DataType)) {
        if (this->monitored_source_name.find(".monitor") != std::string::npos) {
            this->sink_name = this->monitored_source_name;
            this->sink_name.erase(sink_name.find(".monitor"));
        } else {
            std::cerr << "The monitored source name should be a sink monitor"
                      << std::endl;
            return;
        }

        virtual_sink_name = "pa_monitor-" + this->sink_name + "-null_sink-" +
                            generateRandomString(8);

        // Initialize the mainloop and context
        mainloop = pa_threaded_mainloop_new();
        pa_threaded_mainloop_lock(mainloop);

        mainloop_api = pa_threaded_mainloop_get_api(mainloop);
        // the name of the context should be "pa_monitor <sink_name>"
        context = pa_context_new(mainloop_api, "pa_monitor");
        pa_context_connect(context, nullptr, PA_CONTEXT_NOFLAGS, nullptr);

        // Initialize sample specifications
        this->sample_specifications = new pa_sample_spec();
        this->sample_specifications->format = FORMAT;
        this->sample_specifications->rate = RATE;
        this->sample_specifications->channels = CHANNELS;

        // Initialize channel map
        this->channel_map = new pa_channel_map();
        pa_channel_map_init_stereo(this->channel_map);

        pa_context_set_state_callback(
            context, &PulseAudioMonitor::context_state_cb, this);

        pa_threaded_mainloop_unlock(mainloop);
    }

    ~PulseAudioMonitor() { stop(); };

    void run() { pa_threaded_mainloop_start(mainloop); }

    void stop() {
        if (!mainloop)
            return;
        pa_threaded_mainloop_lock(mainloop);

        // destroy streams
        std::cout << "Destroying streams..." << std::endl;
        if (record_stream) {
            pa_stream_disconnect(record_stream);
            pa_stream_unref(record_stream);
            record_stream = nullptr;
        }
        if (playback_stream) {
            pa_stream_disconnect(playback_stream);
            pa_stream_unref(playback_stream);
            playback_stream = nullptr;
        }

        if (context) {
            pa_operation *op;
            if (sink_input_idx != PA_INVALID_INDEX) {
                std::cout << "Redirecting sink input back to original sink..."
                          << std::endl;
                op = pa_context_move_sink_input_by_index(
                    context, sink_input_idx, sink_idx,
                    &PulseAudioMonitor::redirect_sink_input_cb, this);
                // std::cout << "Waiting for operations to complete..."
                //   << std::endl;
                while (true) {
                    pa_operation_state_t state = pa_operation_get_state(op);
                    if (state == PA_OPERATION_RUNNING) {
                        // Operation is still running, wait a bit
                        // std::cout << "yield conttrol..." << std::endl;
                        pa_threaded_mainloop_wait(mainloop);
                    } else if (state == PA_OPERATION_DONE) {
                        // Operation completed successfully
                        // std::cout << "Operation completed." << std::endl;
                        pa_operation_unref(op);
                        break;
                    } else {
                        // Operation failed
                        std::cerr << "Operation failed" << std::endl;
                        pa_operation_unref(op);
                        break;
                    }
                }
            }

            if (virtual_sink_module_idx != PA_INVALID_INDEX) {
                std::cout << "Destroying virtual sink..." << std::endl;
                op = pa_context_unload_module(
                    context, virtual_sink_module_idx,
                    &PulseAudioMonitor::unload_module_cb, this);
                virtual_sink_module_idx = PA_INVALID_INDEX;
                // std::cout << "Waiting for operations to complete..."
                //   << std::endl;
                while (true) {
                    pa_operation_state_t state = pa_operation_get_state(op);
                    if (state == PA_OPERATION_RUNNING) {
                        // Operation is still running, wait a bit
                        // std::cout << "yield conttrol..." << std::endl;
                        pa_threaded_mainloop_wait(mainloop);
                    } else if (state == PA_OPERATION_DONE) {
                        // Operation completed successfully
                        // std::cout << "Operations completed." << std::endl;
                        pa_operation_unref(op);
                        break;
                    } else {
                        // Operation failed
                        std::cerr << "Operation failed" << std::endl;
                        pa_operation_unref(op);
                        break;
                    }
                }
            }

            std::cout << "Disconnecting context..." << std::endl;
            // Perform remaining cleanup tasks
            pa_context_disconnect(context);
            pa_context_unref(context);
            context = nullptr;
        }
        pa_threaded_mainloop_unlock(mainloop);
        pa_threaded_mainloop_stop(mainloop);
        pa_threaded_mainloop_free(mainloop);
        mainloop = nullptr;
    }

    static void unload_module_cb(pa_context *c, int success, void *userdata) {
        std::cout << "unload_module_cb" << std::endl;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        if (success) {
            std::cout << "Virtual sink unloaded successfully." << std::endl;
        } else {
            std::cerr << "Failed to unload virtual sink." << std::endl;
        }
        pa_threaded_mainloop_signal(monitor->mainloop, 0);
    }

    static void redirect_sink_input_cb(pa_context *c, int success,
                                       void *userdata) {
        std::cout << "redirect_sink_input_cb" << std::endl;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        if (success) {
            std::cout << "Sink input redirected successfully." << std::endl;
        } else {
            std::cerr << "Failed to redirect sink input." << std::endl;
        }
        pa_threaded_mainloop_signal(monitor->mainloop, 0);
    }

  public:
    void get_data(std::size_t length, std::vector<DataType> &data) {
        /**
         * @brief Get data from the monitor source
         * @param length: the length of the data to be retrieved. unit:
         * the number of samples
         * @param data: the data to be retrieved, data shape: (length,
         * channels)
         *
         */
        if (data_queue.size() < length * CHANNELS) {
            return;
        }
        data.insert(data.end(), data_queue.begin(),
                    data_queue.begin() + length * CHANNELS);
        data_queue.erase(data_queue.begin(),
                         data_queue.begin() + length * CHANNELS);
    }

    std::size_t queue_length() { return data_queue.size(); }

  private:
    static void context_state_cb(pa_context *c, void *userdata) {
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        switch (pa_context_get_state(c)) {
        case PA_CONTEXT_READY: {
            std::cout << "Context ready." << std::endl;

            // get the sink index and sink input index
            pa_operation *op = pa_context_get_sink_info_by_name(
                c, monitor->sink_name.c_str(),
                &PulseAudioMonitor::get_monitored_sink_idx_cb, monitor);
            pa_operation_unref(op);

        }; break;
        case PA_CONTEXT_FAILED:
        case PA_CONTEXT_TERMINATED:
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            break;
        default:
            break;
        }
    }

    static void get_monitored_sink_idx_cb(pa_context *c, const pa_sink_info *i,
                                          int eol, void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        if (monitor->sink_idx != PA_INVALID_INDEX)
            return;
        monitor->sink_idx = i->index;
        std::cout << "Sink info ready: sink #" << monitor->sink_idx << ": "
                  << monitor->sink_name << std::endl;
        // get the sink input index by sink index
        pa_operation *op = pa_context_get_sink_input_info_list(
            c, &PulseAudioMonitor::get_sink_input_idx_cb, monitor);
        if (!op) {
            std::cerr << "Failed to get sink input info list" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }
        pa_operation_unref(op);
    }

    static void get_sink_input_idx_cb(pa_context *c,
                                      const pa_sink_input_info *i, int eol,
                                      void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        if (monitor->sink_input_idx != PA_INVALID_INDEX)
            return;
        if (i->sink == monitor->sink_idx) {
            monitor->sink_input_idx = i->index;
            std::cout << "Sink input info ready: sink input #"
                      << monitor->sink_input_idx << ": " << i->name
                      << std::endl;
            // Create virtual sink
            pa_operation *op = pa_context_load_module(
                c, "module-null-sink",
                ("sink_name=" + monitor->virtual_sink_name +
                 " "
                 "sink_properties=device.description=NullSink")
                    .c_str(),
                &PulseAudioMonitor::create_virtual_sink_cb, monitor);
            pa_operation_unref(op);
        }
    }

    static void create_virtual_sink_cb(pa_context *c, uint32_t idx,
                                       void *userdata) {
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);

        if (idx == PA_INVALID_INDEX) {
            std::cerr << "Failed to load module" << std::endl;
            return;
        }

        std::cout << "Virtual sink ready: loaded module #" << idx << std::endl;

        monitor->virtual_sink_module_idx = idx;

        pa_operation *op = pa_context_get_sink_info_by_name(
            c, monitor->virtual_sink_name.c_str(),
            &PulseAudioMonitor::get_virtual_sink_idx_cb, monitor);
        if (!op) {
            std::cerr << "Failed to get sink info list" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }
        pa_operation_unref(op);
    }

    static void get_virtual_sink_idx_cb(pa_context *c, const pa_sink_info *i,
                                        int eol, void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        monitor->virtual_sink_idx = i->index;
        std::cout << "Virtual sink info ready: virtual sink #"
                  << monitor->virtual_sink_idx << ": "
                  << monitor->virtual_sink_name << std::endl;
        // move the sink input to the virtual sink
        pa_operation *op = pa_context_move_sink_input_by_index(
            c, monitor->sink_input_idx, monitor->virtual_sink_idx,
            &PulseAudioMonitor::redirect_sink_input_to_virtual_sink_cb,
            monitor);
        pa_operation_unref(op);
    }

    static void redirect_sink_input_to_virtual_sink_cb(pa_context *c,
                                                       int success,
                                                       void *userdata) {
        if (success < 0) {
            std::cerr << "Failed to move sink input" << std::endl;
            return;
        }
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        std::cout << "Move input ready: moved sink input #"
                  << monitor->sink_input_idx << " to virtual sink #"
                  << monitor->virtual_sink_idx << std::endl;

        // get virtual sink monitor source name by idx
        pa_operation *op = pa_context_get_sink_info_by_index(
            c, monitor->virtual_sink_idx,
            &PulseAudioMonitor::get_virtual_sink_monitor_name_cb, monitor);
        pa_operation_unref(op);
    }

    static void get_virtual_sink_monitor_name_cb(pa_context *c,
                                                 const pa_sink_info *i, int eol,
                                                 void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        std::cout << "Virtual sink monitor source ready: "
                  << i->monitor_source_name << std::endl;
        monitor->virtual_sink_monitor_name = i->monitor_source_name;

        // create a recording stream
        monitor->record_stream =
            pa_stream_new(c, "pa_monitor-recording_stream",
                          monitor->sample_specifications, monitor->channel_map);
        if (!monitor->record_stream) {
            std::cerr << "Failed to create recording stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }
        // record from the virtual sink monitor
        int success = pa_stream_connect_record(
            monitor->record_stream, monitor->virtual_sink_monitor_name.c_str(),
            nullptr, PA_STREAM_AUTO_TIMING_UPDATE);
        if (success < 0) {
            std::cerr << "Failed to connect recording stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }
        std::cout << "Connected recording stream to monitor source: "
                  << monitor->virtual_sink_monitor_name << std::endl;

        // set the read callback
        pa_stream_set_read_callback(monitor->record_stream,
                                    &PulseAudioMonitor::stream_read_cb,
                                    monitor);
        // todo: change this to a poll based callback to actively control the
        // delay

        // create a playback stream
        monitor->playback_stream =
            pa_stream_new(c, "pa_monitor-playback_stream",
                          monitor->sample_specifications, monitor->channel_map);
        if (!monitor->playback_stream) {
            std::cerr << "Failed to create playback stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }

        // connect the playback stream to original sink
        pa_buffer_attr buffer_attr;
        buffer_attr.maxlength =
            RATE * CHANNELS * sizeof(DataType); // max delay is 1s
        buffer_attr.tlength = (uint32_t)(monitor->delay_bytes);
        buffer_attr.prebuf = (uint32_t)-1;
        buffer_attr.minreq = (uint32_t)-1;
        buffer_attr.fragsize = (uint32_t)-1;

        pa_stream_flags_t flags = static_cast<pa_stream_flags_t>(
            PA_STREAM_ADJUST_LATENCY | PA_STREAM_AUTO_TIMING_UPDATE);
        success = pa_stream_connect_playback(
            monitor->playback_stream, monitor->sink_name.c_str(), &buffer_attr,
            flags, nullptr, nullptr);
        if (success < 0) {
            std::cerr << "Failed to connect playback stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }
        std::cout << "Connected playback stream to sink: " << monitor->sink_name
                  << std::endl;
    }

    static void stream_read_cb(pa_stream *s, std::size_t length,
                               void *userdata) {
        // constantly read data from the stream and store into local buffer
        // TODO: maybe wait some interval before reading the data to reduce CPU
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        const void *data;
        if (pa_stream_peek(s, &data, &length) < 0) {
            std::cerr << "Failed to peek stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }

        // Get record stream latency
        // pa_usec_t record_latency;
        // int negative;
        // int ret = pa_stream_get_latency(s, &record_latency, &negative);
        // if (ret == 0) {
        //     std::cout << "Record stream latency: " << record_latency
        //               << " microseconds" << std::endl;
        // } else {
        //     std::cerr << "Failed to get record stream latency" << std::endl;
        // }

        int success = pa_stream_write(monitor->playback_stream, data, length,
                                      nullptr, 0, PA_SEEK_RELATIVE);
        if (success < 0) {
            std::cerr << "Failed to write to playback stream" << std::endl;
            monitor->mainloop_api->quit(monitor->mainloop_api, 1);
            return;
        }

        // Get playback stream latency
        // pa_usec_t playback_latency;
        // ret = pa_stream_get_latency(monitor->playback_stream, &playback_latency,
        //                             &negative);
        // if (ret == 0) {
        //     std::cout << "Playback stream latency: " << playback_latency
        //               << " microseconds" << std::endl;
        // } else {
        //     std::cerr << "Failed to get playback stream latency" << std::endl;
        // }

        pa_stream_drop(s);

        // insert data to the queues
        monitor->data_queue.insert(
            monitor->data_queue.end(), static_cast<const DataType *>(data),
            static_cast<const DataType *>(data + length));

        // apply normalization to the chunk of data
        pa_operation *o = pa_context_get_sink_info_by_index(
            monitor->context, monitor->sink_idx,
            &PulseAudioMonitor::get_sink_volume_cb, monitor);
        pa_operation_unref(o);
        o = pa_context_get_sink_input_info(
            monitor->context, monitor->sink_input_idx,
            &PulseAudioMonitor::get_sink_input_volume_cb, monitor);
        pa_operation_unref(o);

        float normalization_factor =
            ((float)PA_VOLUME_NORM / monitor->current_sink_volume) *
            ((float)PA_VOLUME_NORM / monitor->current_sink_input_volume);

        for (std::size_t i = -length / sizeof(DataType); i < 0; i++) {
            monitor->data_queue[monitor->data_queue.size() + i] *=
                normalization_factor;
        }
    }

    static void get_sink_volume_cb(pa_context *c, const pa_sink_info *i,
                                   int eol, void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        monitor->current_sink_volume = i->volume.values[0];
    }

    static void get_sink_input_volume_cb(pa_context *c,
                                         const pa_sink_input_info *i, int eol,
                                         void *userdata) {
        if (eol != 0)
            return;
        auto monitor = static_cast<PulseAudioMonitor *>(userdata);
        monitor->current_sink_input_volume = i->volume.values[0];
    }

  private:
    pa_threaded_mainloop *mainloop = nullptr;
    pa_mainloop_api *mainloop_api = nullptr;
    pa_context *context = nullptr;

    const std::string monitored_source_name;
    std::string sink_name;

    pa_sample_spec *sample_specifications = nullptr;
    pa_channel_map *channel_map = nullptr;
    // Use a FIFO dequeue to store recorded data,
    FixedDeque<DataType> data_queue{RATE * CHANNELS * 20};
    pa_volume_t current_sink_volume = PA_VOLUME_NORM;
    pa_volume_t current_sink_input_volume = PA_VOLUME_NORM;

    uint32_t sink_idx = PA_INVALID_INDEX;
    uint32_t sink_input_idx = PA_INVALID_INDEX;
    uint32_t virtual_sink_module_idx = PA_INVALID_INDEX;
    uint32_t virtual_sink_idx = PA_INVALID_INDEX;
    std::string virtual_sink_name;
    std::string virtual_sink_monitor_name;
    pa_stream *playback_stream = nullptr;
    pa_stream *record_stream = nullptr;
    size_t delay_bytes = 0;
};
