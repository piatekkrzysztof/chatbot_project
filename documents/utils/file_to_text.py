import os
from pypdf import PdfReader
import docx2txt


def extract_text_from_pdf(file_path):
    """
    Wyodębnia tekst z pliku PDF
    """
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        return f"Błąd podczas ekstrakcji PDF: {str(e)}"


def extract_text_from_docx(file_path):
    """
    Wyodrebnia tekst z pliku DOCX
    """
    try:
        text = docx2txt.process(file_path)
        return text.strip()
    except Exception as e:
        return f"Błąd podczas ekstrakcji DOCX: {str(e)}"


def extract_text_from_txt(file_path):
    """
    Odczytuje tekst z pliku TXT
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        return f"Błąd podczas odczytu TXT: {str(e)}"


def extract_text(file_path):
    """
    Wywołuje odpowiednią funkcję na podstawie rozszerzenia pliku.
    """

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    if ext == ".docx":
        return extract_text_from_docx(file_path)
    if ext == ".txt":
        return extract_text_from_txt(file_path)
    else:
        return ""
