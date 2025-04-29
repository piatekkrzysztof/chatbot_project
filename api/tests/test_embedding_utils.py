import pytest
from unittest.mock import patch
from api.utils.embedding_utils import get_embedding, prepare_document_chunks_for_embedding


@pytest.mark.django_db
@patch("api.utils.embedding_utils.openai.Embedding.create")
def test_get_embedding_success(mock_openai):
    # Przygotowanie odpowiedzi mocka
    mock_openai.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }

    text = "Przykładowy tekst"
    embedding = get_embedding(text)

    mock_openai.assert_called_once()
    assert isinstance(embedding, list)
    assert embedding == [0.1, 0.2, 0.3]


@pytest.mark.django_db
@patch("api.utils.embedding_utils.openai.Embedding.create")
def test_get_embedding_error(mock_openai):
    # Wymuszenie wyjątku
    mock_openai.side_effect = Exception("Błąd OpenAI")

    with pytest.raises(ValueError) as excinfo:
        get_embedding("Błędny tekst")

    assert "Błąd generowania embeddingu" in str(excinfo.value)


@pytest.mark.django_db
def test_prepare_document_chunks_for_embedding():
    class FakeChunk:
        def __init__(self, content):
            self.content = content

    chunks = [FakeChunk("tekst 1"), FakeChunk("tekst 2")]
    texts = prepare_document_chunks_for_embedding(chunks)

    assert texts == ["tekst 1", "tekst 2"]
