# -*- coding: utf-8 -*-
"""本番と同じ形で helper -> ffmpeg(pipe:0) を繋ぎ、level 行が流れ続けるかを見る。

本番の play_live_audio と同じ形:
  helper: Popen(stdout=PIPE, stderr=PIPE, bufsize=0)
  ffmpeg: Popen(stdin=helper.stdout, stdout=PIPE, stderr=DEVNULL)
  親が helper.stdout を close し、ffmpeg の stdout を読み続ける
"""
import os, subprocess, sys, threading, time

REL = r"E:\Projects\VRC_Media_Streamer\releases\VRC_Media_Streamer_v2.10.4"
HELPER = os.path.join(REL, "app_audio_capture.exe")
FFMPEG = os.path.join(REL, "ffmpeg.exe")
STILL = os.path.join(REL, "hls_output", "standby.png")

TARGET_PID = 8524  # 利用者が対象にしている Chrome
target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else TARGET_PID

helper = subprocess.Popen(
    [HELPER, "--pid", str(target_pid), "--mode", "include",
     "--rate", "48000", "--channels", "2", "--level", "200",
     "--parent-pid", str(os.getpid())],
    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    bufsize=0)

levels = []
other = []


def pump():
    try:
        for raw in iter(helper.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if "level peak=" in line:
                levels.append((time.time(), line))
            else:
                other.append((time.time(), line))
    except Exception as e:
        other.append((time.time(), "PUMP ERROR: %r" % (e,)))


threading.Thread(target=pump, daemon=True).start()

cmd = [FFMPEG, "-re", "-loop", "1", "-i", STILL,
       "-f", "s16le", "-ar", "48000", "-ac", "2",
       "-thread_queue_size", "1024", "-i", "pipe:0",
       "-filter_complex", "[1:a]volume=1.0[aout]",
       "-map", "0:v:0", "-map", "[aout]",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
       "-b:v", "800k", "-g", "15", "-r", "5",
       "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
       "-fflags", "+nobuffer+flush_packets", "-flush_packets", "1",
       "-muxdelay", "0", "-muxpreload", "0", "-max_interleave_delta", "0",
       "-f", "mpegts", "pipe:1"]

ff = subprocess.Popen(cmd, stdin=helper.stdout, stdout=subprocess.PIPE,
                      stderr=subprocess.DEVNULL, bufsize=0)
helper.stdout.close()

total = [0]


def drain():
    """本番の relay_stream_data 相当。読み続けないと ffmpeg が詰まる。"""
    try:
        while True:
            b = ff.stdout.read(65536)
            if not b:
                break
            total[0] += len(b)
    except Exception:
        pass


threading.Thread(target=drain, daemon=True).start()

t0 = time.time()
for i in range(10):
    time.sleep(1)
    print("  %2ds  level=%-4d  other=%-3d  ffmpeg_out=%8d bytes"
          % (i + 1, len(levels), len(other), total[0]), flush=True)

print("")
print("--- helper stderr (level以外) ---")
for ts, l in other[:10]:
    print("  +%.1fs %s" % (ts - t0, l))
print("")
print("--- level ---")
if levels:
    print("  first: +%.1fs %s" % (levels[0][0] - t0, levels[0][1]))
    print("  last : +%.1fs %s" % (levels[-1][0] - t0, levels[-1][1]))
    print("  count:", len(levels), "(200ms間隔なら10秒で約50本)")
else:
    print("  1本も来ていない")

for p in (ff, helper):
    try:
        p.kill()
    except Exception:
        pass
print("")
print("ffmpeg rc:", ff.poll(), "/ helper rc:", helper.poll())
