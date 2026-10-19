import sys
import io
import fitz

doc = fitz.open(r'd:\Masters\2026-Winter-Semester\Case_Study_Evaluation\Master-AIT_Case-Study_Medical_Evaluation\vr-training-evaluator\VR_Scoring_Weights_Doctor_Review_NBA.pdf')
output_lines = []
output_lines.append(f'Pages: {len(doc)}')
for i, page in enumerate(doc):
    output_lines.append(f'\n=============== PAGE {i+1} ===============')
    words = page.get_text("words")
    lines = {}
    for w in words:
        x0, y0, x1, y1, word, block_no, line_no, word_no = w
        line_key = round(y0)
        if line_key not in lines:
            lines[line_key] = []
        lines[line_key].append((x0, word))
    for y in sorted(lines.keys()):
        line_words = sorted(lines[y], key=lambda t: t[0])
        output_lines.append("  " + " ".join(w for _, w in line_words))

with open(r'd:\Masters\2026-Winter-Semester\Case_Study_Evaluation\Master-AIT_Case-Study_Medical_Evaluation\vr-training-evaluator\read_pdf_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

print("Done - written to read_pdf_output.txt")
