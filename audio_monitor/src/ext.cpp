#include "pa_monitor.hpp" // Make sure this path is correct
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fstream>

namespace py = pybind11;

PYBIND11_MODULE(pa_monitor, m) {
    py::class_<PulseAudioMonitor>(m, "AudioMonitor")
        .def(py::init<const std::string &, float>(),
             py::arg("monitored_stream_name"), py::arg("delay_seconds") = 0.1)
        .def("run", &PulseAudioMonitor::run)
        .def("stop", &PulseAudioMonitor::stop)
        .def("get_data", [](PulseAudioMonitor &self, int n_samples) {
            std::vector<DataType> data;
            self.get_data(n_samples, data);
            return py::array_t<DataType>(data.size(), data.data());
        })
        .def("queue_length", &PulseAudioMonitor::queue_length);
}
