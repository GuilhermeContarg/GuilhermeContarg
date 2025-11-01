from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai
import markdown
from openai import OpenAI
from pypdf import PdfReader
from weasyprint import HTML, CSS
from dotenv import load_dotenv, find_dotenv

try:
    import pymysql
    from pymysql.err import MySQLError
except ImportError:  # pragma: no cover - biblioteca opcional
    pymysql = None
    MySQLError = Exception


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent.parent
env_file = find_dotenv()
if env_file:
    load_dotenv(env_file)
else:
    fallback = ROOT_DIR / "config.env"
    if fallback.exists():
        load_dotenv(fallback)
IMAGE_DIR = BASE_DIR / "temp_images"
DEFAULT_OUTPUT_PDF = BASE_DIR / "ebook_gerado.pdf"
DEFAULT_GOOGLE_MODEL = os.getenv("GOOGLE_GENERATIVE_MODEL", "gemini-2.5-pro")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DB = os.getenv("MYSQL_DB")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_TABLE = os.getenv("MYSQL_EBOOK_TABLE", "ebooks")

IMAGE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
CORS(app)


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    candidates = getattr(response, "candidates", None)
    if not candidates:
        return ""

    collected: List[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None)
        if not parts:
            continue
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str):
                collected.append(part_text)

    return "".join(collected)


def _extract_text_from_uploads(files: Iterable) -> List[str]:
    texts: List[str] = []
    for storage in files:
        filename = (storage.filename or "").lower()
        if filename.endswith(".pdf"):
            pdf_bytes = io.BytesIO(storage.read())
            reader = PdfReader(pdf_bytes)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
        elif filename.endswith(".txt"):
            texts.append(storage.read().decode("utf-8", errors="ignore"))
    return texts


def _connect_mysql() -> Optional["pymysql.Connection"]:
    if not all([MYSQL_HOST, MYSQL_DB, MYSQL_USER, MYSQL_PASSWORD]):
        return None
    if pymysql is None:
        print("[mysql] Biblioteca pymysql nao encontrada. Pulei o armazenamento no banco.")
        return None

    try:
        connection = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            charset="utf8mb4",
            autocommit=True,
        )
        return connection
    except MySQLError as exc:
        print(f"[mysql] Falha ao conectar: {exc}")
        return None


def _ensure_table_exists(connection: "pymysql.Connection") -> None:
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{MYSQL_TABLE}` (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        personality VARCHAR(100),
        input_text LONGTEXT,
        reference_text LONGTEXT,
        markdown LONGTEXT,
        pdf_filename VARCHAR(255),
        pdf_size BIGINT,
        pdf_content LONGBLOB,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    with connection.cursor() as cursor:
        cursor.execute(create_table_sql)


def _store_record_in_mysql(
    personality: str,
    text_content: str,
    references: str,
    markdown_text: str,
    pdf_path: Path,
) -> Tuple[bool, Optional[str]]:
    connection = _connect_mysql()
    if connection is None:
        return False, "Conexao indisponivel."

    try:
        _ensure_table_exists(connection)
        pdf_bytes = pdf_path.read_bytes()
        with connection.cursor() as cursor:
            insert_sql = f"""
            INSERT INTO `{MYSQL_TABLE}`
            (personality, input_text, reference_text, markdown, pdf_filename, pdf_size, pdf_content)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                insert_sql,
                (
                    personality,
                    text_content,
                    references,
                    markdown_text,
                    pdf_path.name,
                    len(pdf_bytes),
                    pdf_bytes,
                ),
            )
        return True, None
    except MySQLError as exc:
        return False, str(exc)
    finally:
        connection.close()


@app.route("/")
def home() -> str:
    return "Backend do gerador de ebooks esta funcionando!"


@app.route("/generate_ebook", methods=["POST"])
def generate_ebook():
    data = request.form
    text_content = (data.get("text_content") or "").strip()
    personality = (data.get("personality") or "neutra").strip()
    google_api_key = (data.get("google_api_key") or "").strip()
    openai_api_key = (data.get("openai_api_key") or "").strip()
    output_path_raw = (data.get("output_path") or "").strip()

    if output_path_raw:
        output_pdf = Path(output_path_raw).expanduser()
        if not output_pdf.is_absolute():
            output_pdf = (BASE_DIR / output_pdf).resolve()
        else:
            output_pdf = output_pdf.resolve()
    else:
        output_pdf = DEFAULT_OUTPUT_PDF

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    if not text_content:
        return jsonify({"error": "Conteudo de texto e obrigatorio."}), 400

    if not google_api_key:
        return jsonify({"error": "Chave API do Google Gemini e obrigatoria."}), 400

    google_model = (data.get("google_model") or "").strip() or DEFAULT_GOOGLE_MODEL
    google_edit_model = (data.get("google_edit_model") or "").strip() or google_model

    try:
        genai.configure(api_key=google_api_key)
        content_model = genai.GenerativeModel(google_model)
        edit_model = genai.GenerativeModel(google_edit_model)
    except Exception as exc:
        return jsonify(
            {
                "error": (
                    "Falha ao inicializar os modelos Gemini "
                    f"({google_model}/{google_edit_model}): {exc}"
                )
            }
        ), 400

    uploaded_text: List[str] = []
    if "files" in request.files:
        uploaded_text = _extract_text_from_uploads(request.files.getlist("files"))

    references = "\n".join(uploaded_text).strip()

    content_prompt = f"""
Atue como um escritor profissional de ebooks com a personalidade {personality}.
Use EXCLUSIVAMENTE o conteudo principal e as referencias fornecidas para elaborar um manuscrito completo e altamente profissional.

Conteudo principal:
{text_content}

Referencias adicionais:
{references or 'Nenhuma'}

Diretrizes obrigatorias:
- Construa uma narrativa coesa com introducao, capitulos bem estruturados, subtitulos quando fizer sentido e uma conclusao forte.
- Nao introduza informacoes externas, opinioes ou historias que nao estejam no material fornecido.
- não inclua no texto a frase: Gerado pelo seu agente de ebooks.
- não inclua no texto comentario sobre o conteudo do texto principal.
- não inclua comentarios iniciais no texto, antes de começar o conteudo.
- faça um sumario conciso e envolvente para o inicio do ebook.
- faça o indice do ebook, listando os titulos dos capitulos e suas respectivas paginas.
- Melhore a estrutura geral, reorganizando secoes se necessario para melhor fluxo logico.
- Remova redundancias e informacoes irrelevantes.
- faça a quebra de conteudo para garantir que todos os pontos importantes sejam abordados de forma completa.
- faça a quebra de pagina nas mudanças de capitulo ou secoes principais.
- toda a vez que for fazer uma quebra de pagina, faça uma quebra de seção.
- toda a vez que for começar um novo capitulo, faça uma quebra de seção.e começe numa nova pagina
- Use o modelo de storytelling a seguir para estruturar a narrativa quando aplicavel:(lembrando que isso é apenas um guia e nem todas as historias precisam seguir todos os elementos)
        - Personagem: O "quem". O protagonista com quem o público se identifica.
        - Objetivo (ou Desejo): O "o quê". O que o personagem principal quer alcançar.
        - Conflito: O "porquê não". O obstáculo, vilão ou problema que impede o personagem de atingir seu objetivo.
        - Jornada (Trama): O "como". A sequência de eventos e desafios que testam o personagem.
        - Tensão: A construção da expectativa e do risco, o que mantém o público engajado.
        - Clímax: O ponto de virada decisivo; a batalha final ou o confronto máximo.
        - Resolução: O resultado do clímax e o fechamento da história.
        - Transformação: A mudança interna que o personagem sofre; a lição aprendida.
- Nao crie secoes de credito, autor, agradecimentos ou qualquer mensagem sobre geracao automatica.
- Nao inclua linhas dedicadas a numero de pagina ou notas internas.
- Utilize Markdown puro e direto, sem comentarios ou textos explicativos adicionais.
- Adote tom corporativo, convincente e refinado.
""".strip()

    try:
        content_response = content_model.generate_content(content_prompt)
    except Exception as exc:
        return jsonify({"error": f"Falha ao gerar o rascunho do ebook: {exc}"}), 500

    raw_markdown = _response_text(content_response).strip()
    if not raw_markdown:
        return jsonify({"error": "O modelo nao retornou texto para o rascunho."}), 500

    edit_prompt = f"""
Voce agora e um editor senior de publicacoes profissionais com a personalidade {personality}.
Revise o rascunho a seguir e garanta que ele permaneca fiel ao material original sem adicionar fatos externos.

Rascunho recebido:
{raw_markdown}

Diretrizes de edicao:
- Eleve a clareza, a fluidez e a coerencia preservando o significado original.
- Corrija erros de gramatica, ortografia, pontuacao e estilo.
- Ajuste o Markdown para manter cabecalhos consistentes, paragrafos equilibrados e listas claras quando apropriado.
- Elimine qualquer referencia a autores, fontes, ferramentas ou processos de geracao.
- Entregue somente o Markdown final, pronto para diagramacao.
""".strip()

    try:
        edit_response = edit_model.generate_content(edit_prompt)
        ebook_markdown = _response_text(edit_response).strip() or raw_markdown
    except Exception as exc:
        print(f"[generate_ebook] Falha ao editar rascunho: {exc}")
        ebook_markdown = raw_markdown

    cover_image_html = ""
    if openai_api_key:
        try:
            client = OpenAI(api_key=openai_api_key)
            first_heading = raw_markdown.splitlines()[0].strip("# ").strip() if raw_markdown else ""
            cover_title = first_heading or "Capa de ebook"
            image_prompt = (
                f"Capa de ebook com estetica profissional sobre {cover_title}, "
                f"alinhada a uma personalidade {personality}."
            )

            image_response = client.images.generate(
                model="gpt-image-1",
                prompt=image_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
                response_format="b64_json",
            )

            image_b64 = image_response.data[0].b64_json
            image_path = IMAGE_DIR / "cover_image.png"
            with image_path.open("wb") as image_file:
                image_file.write(base64.b64decode(image_b64))

            cover_image_html = (
                f'<img src="data:image/png;base64,{image_b64}" '
                'alt="Capa do Ebook" style="width: 100%; page-break-after: always;">\n'
            )
        except Exception as exc:
            print(f"[generate_ebook] Falha ao gerar imagem de capa: {exc}")

    html_body = markdown.markdown(ebook_markdown)

    css = """
    @page {
        size: A4;
        margin: 1in;
    }
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        line-height: 1.8;
        color: #2c3e50;
        background-color: #f9f9f9;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #34495e;
        margin-top: 1.5em;
        margin-bottom: 0.8em;
        font-weight: bold;
    }
    h1 {
        font-size: 2.8em;
        text-align: center;
        color: #2980b9;
        page-break-before: always;
        padding-top: 2em;
        padding-bottom: 1em;
        background-color: #ecf0f1;
        border-radius: 10px;
    }
    h2 {
        font-size: 2.2em;
        color: #2c3e50;
        border-bottom: 2px solid #3498db;
        padding-bottom: 5px;
        margin-top: 2em;
    }
    h3 {
        font-size: 1.7em;
        color: #34495e;
        margin-top: 1.5em;
    }
    p {
        margin-bottom: 1em;
        text-align: justify;
    }
    ul, ol {
        margin-left: 20px;
        margin-bottom: 1em;
    }
    li {
        margin-bottom: 0.5em;
    }
    blockquote {
        border-left: 5px solid #3498db;
        padding-left: 15px;
        margin-left: 20px;
        font-style: italic;
        color: #555;
    }
    code {
        font-family: monospace;
        background-color: #ecf0f1;
        padding: 2px 4px;
        border-radius: 3px;
    }
    pre {
        background-color: #ecf0f1;
        padding: 10px;
        border-radius: 5px;
        overflow-x: auto;
        margin-bottom: 1em;
    }
    img {
        max-width: 100%;
        height: auto;
        display: block;
        margin: 1.5em auto;
        border: 1px solid #ccc;
        border-radius: 5px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    """.strip()

    html_document = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
    </head>
    <body>
        {cover_image_html}
        {html_body}
    </body>
    </html>
    """.strip()

    try:
        HTML(string=html_document, base_url=str(BASE_DIR)).write_pdf(
            str(output_pdf), stylesheets=[CSS(string=css)]
        )
    except Exception as exc:
        return jsonify({"error": f"Falha ao gerar o PDF: {exc}"}), 500

    store_ok, store_error = _store_record_in_mysql(
        personality=personality,
        text_content=text_content,
        references=references,
        markdown_text=ebook_markdown,
        pdf_path=output_pdf,
    )
    if not store_ok and store_error:
        print(f"[mysql] Nao foi possivel salvar o registro: {store_error}")

    return send_file(
        str(output_pdf),
        as_attachment=True,
        download_name=output_pdf.name,
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
