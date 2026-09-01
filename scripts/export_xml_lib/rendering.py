import os
import subprocess
from .utils import get_video_dims

def render_segmented_overlays(ass_path, segments, video_path, output_dir):
    """
    Renders segments using a physical transparent PNG canvas to ensure alpha correctness.
    """
    width, height, _, fps = get_video_dims(video_path)
    ass_path_sanitized = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    
    # Generate Base Canvas
    canvas_png = os.path.join(output_dir, "base_canvas.png")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black@0.0:s={width}x{height}", 
        "-frames:v", "1", "-c:v", "png", canvas_png
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    
    overlay_data = []
    print(f"Rendering {len(segments)} subtitle segments (Mode: Canvas + QTRLE)...")
    
    for i, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        if duration <= 0: continue
        
        filename = f"caption_{i}.mov"
        out_path = os.path.join(output_dir, filename)
        
        # QTRLE (QuickTime Animation) - The absolute reference for Alpha.
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", canvas_png,
            "-vf", f"format=rgba,setpts=PTS+{start}/TB,ass='{ass_path_sanitized}',setpts=PTS-{start}/TB,format=rgba",
            "-t", str(duration),
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            "-an",
            out_path
        ]
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                rel_path = os.path.join("captions", filename).replace("\\", "/")
                overlay_data.append({ "path": rel_path, "start": start, "end": end, "index": i })
                print(f"  [Seg {i}] Rendered {duration:.2f}s")
            else:
                print(f"  [Seg {i}] Rendered output is invalid or empty.")
        except subprocess.CalledProcessError as e:
            stderr_info = e.stderr.decode(errors='replace') if e.stderr else str(e)
            print(f"  [Seg {i}] Failed: {stderr_info}")
            if os.path.exists(out_path):
                try: os.remove(out_path)
                except Exception: pass
            
    if os.path.exists(canvas_png):
        try: os.remove(canvas_png)
        except Exception: pass

    return overlay_data
