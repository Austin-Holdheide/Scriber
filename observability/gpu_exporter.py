#!/usr/bin/env python3
"""Tiny GPU metrics exporter for LXC-passthrough NVIDIA GPUs (no docker needed)."""
import http.server
import subprocess

PORT = 9400
QUERY = "index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def metrics() -> str:
    try:
        out = subprocess.run(
            ["/usr/local/bin/nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return "# gpu unavailable\n"
    lines = []
    for idx, row in enumerate(out.splitlines()):
        p = [x.strip() for x in row.split(",")]
        if len(p) < 7:
            continue
        name, util, mem_used, mem_total, temp, power = p[1], p[2], p[3], p[4], p[5], p[6]
        lbl = f'{{gpu="{idx}",name="{name}"}}'
        def num(x):
            try: return float(x)
            except ValueError: return 0.0
        lines.append(f"nvidia_utilization_percent{lbl} {num(util)}")
        lines.append(f"nvidia_memory_used_mib{lbl} {num(mem_used)}")
        lines.append(f"nvidia_memory_total_mib{lbl} {num(mem_total)}")
        lines.append(f"nvidia_temperature_celsius{lbl} {num(temp)}")
        lines.append(f"nvidia_power_watts{lbl} {num(power)}")
    return "\n".join(lines) + "\n"


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", PORT), H).serve_forever()
