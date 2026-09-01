import json
import os

def process_segments(data, start_time, end_time):
    new_segments = []
    
    for segment in data.get('segments', []):
        seg_start = float(segment.get('start', 0))
        seg_end = float(segment.get('end', 0))
        
        # Verifica interseção
        if seg_end <= start_time or seg_start >= end_time:
            continue
            
        # Calcula overlap
        # Ajusta timestamps relativos ao corte
        new_seg_start = max(0.0, seg_start - start_time)
        new_seg_end = min(end_time, seg_end) - start_time
        
        if new_seg_end <= new_seg_start:
            continue
            
        # Filtra palavras se existirem
        new_words = []
        if 'words' in segment and isinstance(segment['words'], list) and segment['words']:
            for word in segment['words']:
                w_start = float(word.get('start', 0))
                w_end = float(word.get('end', 0))
                
                if w_end > start_time and w_start < end_time:
                    new_w_start = max(0.0, w_start - start_time)
                    new_w_end = min(end_time, w_end) - start_time
                    word_copy = word.copy()
                    word_copy['start'] = round(new_w_start, 3)
                    word_copy['end'] = round(new_w_end, 3)
                    new_words.append(word_copy)
        
        # Fallback de síntese de palavras caso 'words' esteja vazio/ausente mas haja texto
        if not new_words and segment.get('text', '').strip():
            text_tokens = segment['text'].strip().split()
            if text_tokens:
                n_tokens = len(text_tokens)
                dur = new_seg_end - new_seg_start
                step = dur / n_tokens
                for idx, tok in enumerate(text_tokens):
                    tok_start = new_seg_start + idx * step
                    tok_end = new_seg_start + (idx + 1) * step if idx < n_tokens - 1 else new_seg_end
                    new_words.append({
                        'word': tok,
                        'start': round(tok_start, 3),
                        'end': round(tok_end, 3),
                        'score': 1.0
                    })

        # Se sobraram palavras ou se o segmento é válido no tempo
        if new_words or (new_seg_end > new_seg_start):
            new_segment = segment.copy()
            new_segment['start'] = round(new_seg_start, 3)
            new_segment['end'] = round(new_seg_end, 3)
            if new_words:
                new_segment['words'] = new_words
            elif 'words' in new_segment:
                del new_segment['words']
            new_segments.append(new_segment)
            
    return {'segments': new_segments}

def cut_json_transcript(input_json_path, output_json_path, start_time, end_time):
    """
    Lê o input.json (WhisperX), recorta o trecho e salva em output_json_path com timestamps ajustados.
    """
    if not os.path.exists(input_json_path):
        print(f"Aviso: {input_json_path} não encontrado. Não foi possível gerar JSON do corte.")
        return

    try:
        with open(input_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        new_data = process_segments(data, start_time, end_time)
        
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
            
        print(f"JSON de legenda gerado: {output_json_path}")
        
    except Exception as e:
        print(f"Erro ao cortar JSON: {e}")
