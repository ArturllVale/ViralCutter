import os
import json
import shutil
import re
from i18n.i18n import I18nAuto
from scripts.download_video import validate_video_file

i18n = I18nAuto()

def sanitize_filename(name):
    """Remove caracteres inválidos para nomes de arquivos/pastas no Windows."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = cleaned.strip()
    return cleaned if cleaned else "Viral_Segment"

def organize(project_folder="tmp"):
    print(i18n("Organizing output files..."))
    
    meta_path = os.path.join(project_folder, "viral_segments.txt")
    burned_folder = os.path.join(project_folder, "burned_sub")
    final_folder = os.path.join(project_folder, "final")
    virals_root = os.path.join(project_folder, "virals_organized")
    
    if not os.path.exists(meta_path):
        print(i18n("Metadata file not found: ") + meta_path)
        return
        
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            segments = data.get("segments", [])
    except Exception as e:
        print(i18n("Error reading metadata: ") + str(e))
        return

    os.makedirs(virals_root, exist_ok=True)
    processed_count = 0
    
    for i, segment in enumerate(segments):
        title = segment.get("title", f"Viral_Segment_{i+1}")
        clean_title = sanitize_filename(title)
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip().replace(" ", "_")[:60]
        if not safe_title:
            safe_title = f"Segment_{i}"
            
        base_name = f"{i:03d}_{safe_title}"

        # Cria pasta do viral
        viral_folder = os.path.join(virals_root, f"{i:03d}_{clean_title}")
        os.makedirs(viral_folder, exist_ok=True)
        
        # Procura arquivo fonte
        candidate_sources = [
            os.path.join(burned_folder, f"{base_name}_subtitled.mp4"),
            os.path.join(burned_folder, f"{base_name}_processed_subtitled.mp4"),
            os.path.join(burned_folder, f"output{str(i).zfill(3)}_original_scale_subtitled.mp4"),
            os.path.join(final_folder, f"{base_name}.mp4"),
            os.path.join(final_folder, f"{base_name}_processed.mp4"),
            os.path.join(final_folder, f"output{str(i).zfill(3)}_original_scale.mp4"),
        ]
        
        source_video = None
        for candidate in candidate_sources:
            if validate_video_file(candidate):
                source_video = candidate
                break

        if not source_video:
            print(i18n(f"Warning: Could not find valid video file for segment {i+1} ({title})"))
            continue
            
        # Define caminhos finais
        target_video = os.path.join(viral_folder, f"{clean_title}.mp4")
        target_json = os.path.join(viral_folder, f"{clean_title}.json")
        
        try:
            if not os.path.exists(target_video) or not validate_video_file(target_video):
                shutil.copy2(source_video, target_video)
        except Exception as e:
            print(i18n(f"Error copying video for segment {i}: {e}"))
            continue
            
        try:
            with open(target_json, 'w', encoding='utf-8') as f:
                json.dump(segment, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(i18n(f"Error saving JSON for segment {i}: {e}"))
            
        processed_count += 1
        print(i18n(f"Saved: {clean_title}"))

    print(i18n(f"Organization completed. {processed_count} virals saved in '{virals_root}' folder."))

if __name__ == "__main__":
    organize()
