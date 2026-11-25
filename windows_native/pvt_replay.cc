// Replay the seven-double Hybrid_Observables dump into the native RTKLIB_PVT sink.
#include "file_configuration.h"
#include "gnss_synchro.h"
#include "rtklib_pvt.h"
#include "gnss_sdr_make_unique.h"
#include <boost/archive/xml_iarchive.hpp>
#include <boost/serialization/map.hpp>
#include <gnuradio/sync_block.h>
#include <gnuradio/top_block.h>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
class Observations : public gr::sync_block
{
public:
    Observations(const std::filesystem::path& file, std::vector<std::string> channels)
        : gr::sync_block("Saved observations", gr::io_signature::make(0, 0, 0),
              gr::io_signature::make(channels.size(), channels.size(), sizeof(Gnss_Synchro))),
          stream_(file, std::ios::binary), channels_(std::move(channels)), frame_(channels_.size())
    {
        if (!stream_) throw std::runtime_error("Cannot open observations");
    }

    int work(int requested, gr_vector_const_void_star&, gr_vector_void_star& outputs) override
    {
        int count = 0;
        for (; count < requested; ++count)
            {
                if (!stream_.read(reinterpret_cast<char*>(frame_.data()),
                        static_cast<std::streamsize>(frame_.size()*sizeof(frame_[0]))))
                    break;
                for (size_t ch = 0; ch < channels_.size(); ++ch)
                    {
                        const auto& values = frame_[ch];
                        Gnss_Synchro item{};
                        const auto& id = channels_[ch];
                        item.Channel_ID = static_cast<int32_t>(ch);
                        item.System = id[0];
                        item.Signal[0] = id[1];
                        item.Signal[1] = id[2];
                        if (values[6] == 1 && std::isfinite(values[4]) && values[4] > 0 &&
                            values[5] >= 1 && values[5] <= 255 &&
                            std::isfinite(values[0]) && std::isfinite(values[1]))
                            {
                                item.RX_time = values[0];
                                item.interp_TOW_ms = values[1]*1000;
                                item.Carrier_Doppler_hz = values[2];
                                item.Carrier_phase_rads = values[3]*6.283185307179586;
                                item.Pseudorange_m = values[4];
                                item.PRN = static_cast<uint32_t>(values[5]);
                                item.Flag_valid_pseudorange = true;
                                item.Flag_valid_word = true;
                                item.Flag_valid_symbol_output = true;
                            }
                        static_cast<Gnss_Synchro*>(outputs[ch])[count] = item;
                    }
            }
        return count ? count : -1;
    }

private:
    std::ifstream stream_;
    std::vector<std::string> channels_;
    std::vector<std::array<double,7>> frame_;
};

template<class T>
void post_navigation(const gr::basic_block_sptr& sink, const std::filesystem::path& path,
    const char* tag, const char* signal = nullptr)
{
    std::ifstream stream(path);
    if (!stream) return;
    boost::archive::xml_iarchive archive(stream);
    std::map<int,T> rows;
    archive >> boost::serialization::make_nvp(tag, rows);
    for (const auto& row : rows)
        {
            auto msg = pmt::make_any(std::make_shared<T>(row.second));
            if (signal) msg = pmt::cons(pmt::mp(signal), msg);
            sink->_post(pmt::mp("telemetry"), msg);
        }
}
}  // namespace

int main(int argc, char** argv)
{
    try
        {
            if (argc < 4) throw std::runtime_error("Usage: pvt-replay config observations-directory [system+signal ...]");
            FileConfiguration config(argv[1]);
            const auto input = std::filesystem::u8path(argv[2]);
            std::vector<std::string> channels(argv+3, argv+argc);
            for (const auto& id : channels)
                if (id.size() != 3) throw std::runtime_error("Invalid observation channel map");
            Rtklib_Pvt pvt(&config,"PVT",channels.size(),0);
            const auto sink = pvt.get_left_block();
            post_navigation<Gps_Ephemeris>(sink,input/"gps_ephemeris.xml","GNSS-SDR_ephemeris_map");
            post_navigation<Gps_CNAV_Ephemeris>(sink,input/"gps_cnav_ephemeris.xml","GNSS-SDR_cnav_ephemeris_map");
            post_navigation<Galileo_Ephemeris>(sink,input/"gal_ephemeris.xml","GNSS-SDR_gal_ephemeris_map");
            post_navigation<Glonass_Gnav_Ephemeris>(sink,input/"glo_gnav_ephemeris.xml","GNSS-SDR_gnav_ephemeris_map");
            post_navigation<Beidou_Dnav_Ephemeris>(sink,input/"bds_dnav_ephemeris.xml","GNSS-SDR_bds_dnav_ephemeris_map");
            post_navigation<Beidou_Cnav1_Ephemeris>(sink,input/"bds_cnav1_ephemeris.xml","GNSS-SDR_bds_cnav1_ephemeris_map");
            post_navigation<Beidou_Cnav1_Ephemeris>(sink,input/"bds_cnav2_ephemeris.xml","GNSS-SDR_bds_cnav2_ephemeris_map");
            auto stream = gnuradio::make_block_sptr<Observations>(input/"observables.dat",channels);
            const auto graph = gr::make_top_block("Offline positioning");
            for (size_t ch = 0; ch < channels.size(); ++ch)
                graph->connect(stream,ch,sink,ch);
            graph->run();
            return 0;
        }
    catch (const std::exception& error)
        {
            std::cerr << error.what() << '\n';
            return 1;
        }
}
