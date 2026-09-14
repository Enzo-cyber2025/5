#!/usr/bin/env python3
"""Build an independent, real-weight single-file fixture OUTSIDE the Android app.
Not a public pre-unified model download. Never commit the weights to Git.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('.cache/standalone-500m')
REV = '72e986006ef53e37cdd3f6d4241c90b0f01df376'
REPO = 'ggml-org/SmolVLM-500M-Instruct-GGUF'
SOURCES = [
    ('SmolVLM-500M-Instruct-Q8_0.gguf', 436806912, '9d4612de6a42214499e301494a3ecc2be0abdd9de44e663bda63f1152fad1bf4'),
    ('mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 108783360, 'd1eb8b6b23979205fdf63703ed10f788131a3f812c7b1f72e0119d5d81295150'),
]


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    sys.path.insert(0, str(Path('.cache/llama-mobile/gguf-py').resolve()))
    from gguf import GGUFReader, GGUFWriter, GGUFValueType
    ROOT.mkdir(parents=True, exist_ok=True)
    evidence = Path('evidence'); evidence.mkdir(exist_ok=True)
    for name, size, sha in SOURCES:
        path = ROOT / name
        if not path.exists() or path.stat().st_size != size or digest(path) != sha:
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--max-time', '900',
                            f'https://huggingface.co/{REPO}/resolve/{REV}/{name}', '-o', str(path)], check=True)
        assert path.stat().st_size == size and digest(path) == sha, name

    def tensors(reader):
        return {t.name: {'shape': t.shape.tolist(), 'type': int(t.tensor_type),
                         'sha256': hashlib.sha256(t.data).hexdigest()} for t in reader.tensors}

    language, vision = (GGUFReader(str(ROOT / source[0])) for source in SOURCES)
    expected = tensors(language); visual = tensors(vision)
    assert not set(expected) & set(visual)
    expected.update(visual)
    out = ROOT / 'model.gguf'  # Neutral import filename, no modality hints.
    writer = GGUFWriter(out, language.fields['general.architecture'].contents())
    for reader in (language, vision):
        for key, field in reader.fields.items():
            if key.startswith('GGUF.') or key == 'general.alignment':
                continue
            if reader is vision and key in language.fields:
                continue
            writer.add_key_value(key, field.contents(), field.types[0],
                                 field.types[-1] if field.types[0] == GGUFValueType.ARRAY else None)
    writer.add_name('SmolVLM-500M-Instruct independent single-file')
    for reader in (language, vision):
        for tensor in reader.tensors:
            writer.add_tensor(tensor.name, tensor.data, raw_dtype=tensor.tensor_type)
    writer.write_header_to_file(); writer.write_kv_data_to_file()
    writer.write_tensors_to_file(); writer.close()
    combined = GGUFReader(str(out))
    assert tensors(combined) == expected
    assert combined.fields['clip.has_vision_encoder'].contents() is True
    assert not any(k.startswith('ggufchat.') for k in combined.fields)
    result = {'status': 'PASS', 'origin': 'Independent upstream GGUFWriter repackaging of real pretrained weights, NOT a public pre-unified download',
              'repo': REPO, 'revision': REV, 'output_file': str(out), 'size': out.stat().st_size,
              'sha256': digest(out), 'language_tensors': len(language.tensors),
              'vision_tensors': len(vision.tensors), 'tensor_count': len(expected),
              'sources': [{'file': n, 'size': size, 'sha256': sha} for n, size, sha in SOURCES],
              'architecture': combined.fields['general.architecture'].contents(),
              'projector_type': combined.fields['clip.projector_type'].contents(),
              'private_app_metadata': False, 'tensors': expected}
    # Once the output has been audited, remove the two source files BEFORE Android starts.
    # These are only the fixed files in this script's private disposable cache directory.
    for name, _, _ in SOURCES:
        (ROOT / name).unlink()
    assert list(ROOT.glob('*.gguf')) == [out]
    result['source_files_removed_before_emulator'] = True
    (evidence / 'physical-standalone-fixture.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != 'tensors'}, indent=2))


if __name__ == '__main__':
    main()
