"""Private subprocess entry point. No Django settings, environment files or secrets."""

import base64
import json
import pathlib
import sys


def main():
    # All arguments are constructed by isolated_parser from installed code paths;
    # filenames, URLs, user-supplied options and environment values never become code.
    mode, suffix, memory, dependencies = sys.argv[1:]
    sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent.parent), *json.loads(dependencies)]
    from documents.parser_limits import apply_limits

    try:
        apply_limits(int(memory))
    except (OSError, ValueError):
        print(json.dumps({"error": "unavailable"}))
        return 2

    from documents.file_limits import (
        MAX_DOCUMENT_BYTES,
        InvalidUpload,
        UploadTooLarge,
        check_extracted_text,
        check_text,
        extract_docx,
        inspect_document,
        normalize_image,
    )

    try:
        data = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
        if mode == "image":
            value = {"image": base64.b64encode(normalize_image(data, "image" + suffix)).decode()}
        else:
            inspect_document(data, "document" + suffix)
            if suffix == ".pdf":
                import io

                from pypdf import filters

                from documents.file_limits import MAX_PDF_STREAM_BYTES
                from documents.utils.pdf_parser import extract_text_from_pdf

                for limit in (
                    "MAX_DECLARED_STREAM_LENGTH",
                    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
                    "JBIG2_MAX_OUTPUT_LENGTH",
                    "LZW_MAX_OUTPUT_LENGTH",
                    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
                    "ZLIB_MAX_OUTPUT_LENGTH",
                    "FLATE_MAX_BUFFER_SIZE",
                ):
                    setattr(filters, limit, MAX_PDF_STREAM_BYTES)
                text = extract_text_from_pdf(io.BytesIO(data))
            elif suffix == ".docx":
                text = extract_docx(data)
            else:
                text = check_text(data)
            value = {"text": check_extracted_text(text)}
        sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        return 0
    except UploadTooLarge as error:
        print(json.dumps({"error": "limit", "message": str(error)}))
    except InvalidUpload as error:
        print(json.dumps({"error": "invalid", "message": str(error)}))
    except Exception:
        # Parser exceptions may contain file contents and internal paths.
        print(json.dumps({"error": "invalid"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
