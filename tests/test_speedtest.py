import http.server
import threading

import pytest

import speedtest


PAYLOAD_SIZE = 512 * 1024


class PayloadHandler(http.server.BaseHTTPRequestHandler):
    payload = b"x" * PAYLOAD_SIZE

    def do_GET(self):
        if self.path != "/data.bin":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/data.bin"
    server.shutdown()
    thread.join()


def test_fetch_returns_correct_size(server_url):
    sample = speedtest.fetch(server_url, timeout=5)
    assert sample.size_bytes == PAYLOAD_SIZE


def test_fetch_measures_positive_time(server_url):
    sample = speedtest.fetch(server_url, timeout=5)
    assert sample.total_seconds > 0
    assert sample.ttfb_seconds > 0
    assert sample.ttfb_seconds <= sample.total_seconds


def test_fetch_raises_on_http_error(server_url):
    with pytest.raises(speedtest.urllib.error.HTTPError):
        speedtest.fetch(server_url + "/missing.bin", timeout=5)


def test_run_collects_all_samples(server_url):
    report = speedtest.run(server_url, count=3, timeout=5)
    assert len(report.samples) == 3
    assert report.failures == 0
    assert report.total_bytes == 3 * PAYLOAD_SIZE


def test_report_math(server_url):
    report = speedtest.run(server_url, count=2, timeout=5)
    assert report.avg_time_seconds == pytest.approx(
        sum(s.total_seconds for s in report.samples) / 2
    )
    assert report.avg_speed_mb_per_sec == pytest.approx(
        report.total_bytes / speedtest.MB / report.total_seconds
    )


def test_report_json_shape(server_url):
    report = speedtest.run(server_url, count=1, timeout=5)
    data = report.as_dict()
    assert data["requests"] == 1
    assert data["total_bytes"] == PAYLOAD_SIZE
    assert data["avg_speed_mb_per_sec"] > 0


def test_cli_human_output(server_url, capsys):
    code = speedtest.main([server_url, "-n", "2"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Average speed" in out
    assert "MB/s" in out


def test_cli_json_output(server_url, capsys):
    import json
    code = speedtest.main([server_url, "-n", "1", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["requests"] == 1


def test_cli_rejects_bad_args():
    with pytest.raises(SystemExit):
        speedtest.parse_args(["http://example.com", "-n", "0"])
