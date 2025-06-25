# Copyright (c) Opendatalab. All rights reserved.

import base64
import os
import re
import time
import zipfile
from pathlib import Path
import shutil
import asyncio
import tempfile # For creating a unique directory for app instance
from typing import Tuple, Optional, Any # For type hinting

import gradio as gr # type: ignore
from gradio_pdf import PDF # type: ignore
from loguru import logger

# Updated imports:
# Assuming src.mineru is in PYTHONPATH or app is run from mineru_gradio_service/
from src.mineru.api import MinerUClient
from src.mineru.utils.hash_utils import str_sha256
# `src.mineru.config` will be implicitly loaded by MinerUClient, handling .env vars.

# Path to a directory for temporary files created by this app instance
# This helps in managing files created by Gradio uploads or intermediate processing steps.
APP_TEMP_DIR = Path(tempfile.gettempdir()) / f"mineru_gradio_app_{os.getpid()}"
APP_TEMP_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"Gradio app temporary directory: {APP_TEMP_DIR}")

# --- Helper Functions ---
def read_file_bytes(file_path: Path) -> bytes:
    """Reads a file and returns its byte content."""
    with open(file_path, "rb") as f:
        return f.read()

async def parse_document_via_client(
    doc_path: Path,
    client_processing_output_dir: Path, # Dir where client will store its batch output
    max_pages: int,
    is_ocr: bool,
    language: str
    # formula_enable, table_enable are not directly used by current MinerUClient interface
) -> Tuple[str, str, Optional[str]]:
    """
    Uses MinerUClient to parse the document.
    Returns: (content_directory_path, markdown_file_stem, layout_pdf_path_or_none)
    """
    client = MinerUClient()

    page_ranges_str: Optional[str] = None
    # Max pages slider has 0 for "all pages". MinerUClient expects None for all pages.
    if max_pages > 0:
        page_ranges_str = f"1-{max_pages}"

    try:
        file_processing_details = {
            "path": str(doc_path),
            "is_ocr": is_ocr,
            "page_ranges": page_ranges_str,
        }

        client_processing_output_dir.mkdir(exist_ok=True, parents=True)

        logger.info(f"Starting document processing with MinerUClient for: {doc_path}")
        logger.info(f"Params: is_ocr={is_ocr}, language={language}, page_ranges={page_ranges_str}, client_output_to={client_processing_output_dir}")

        # Directly call submit_file_task and manage polling to ensure language is passed.
        # This bypasses process_file_to_markdown's current limitation with language passthrough.
        task_submission_info = await client.submit_file_task(
            files=[file_processing_details],
            enable_ocr=is_ocr,
            language=language
        )

        batch_id = task_submission_info["data"]["batch_id"]
        logger.info(f"Submitted task to MinerUClient. Batch ID: {batch_id}")

        max_retries = 180
        retry_interval = 10
        for i in range(max_retries):
            status_info = await client.get_batch_task_status(batch_id)
            logger.debug(f"Polling status for batch {batch_id} (attempt {i+1}/{max_retries}): {status_info}")

            if status_info.get("data", {}).get("extract_result"):
                all_tasks_in_batch_completed = True
                for res_item in status_info["data"]["extract_result"]:
                    if res_item.get("state") not in ["done", "failed", "error"]:
                        all_tasks_in_batch_completed = False
                        break
                if all_tasks_in_batch_completed:
                    logger.info(f"All tasks in batch {batch_id} completed.")
                    break
            await asyncio.sleep(retry_interval)
        else:
            logger.error(f"Batch task {batch_id} timed out after {max_retries} retries.")
            raise TimeoutError(f"Batch task {batch_id} timed out.")

        final_status_info = await client.get_batch_task_status(batch_id)
        # This private method usage is a workaround for language parameter.
        # Ideally, MinerUClient.process_file_to_markdown would be enhanced or a new public method provided.
        download_results_list, batch_extract_dir = client._MinerUClient__download_and_extract_results_sync( # type: ignore
            batch_id,
            final_status_info["data"]["extract_result"],
            client_processing_output_dir
        )

        client_run_results = {
            "results": download_results_list,
            "extract_dir": batch_extract_dir, # Base directory for this batch_id's extracted files
        }
        logger.info(f"MinerUClient processing finished. Results structure: {client_run_results}")

        if not client_run_results or not client_run_results.get("results"):
            raise Exception("Invalid or empty response from MinerUClient processing.")

        first_result = client_run_results["results"][0]
        if first_result.get("status") == "success":
            # extract_path is the specific directory for this file's results (e.g., .../batch_id/zip_file_name_without_ext/)
            extracted_content_path = Path(first_result["extract_path"])
            md_files = list(extracted_content_path.glob("*.md"))
            if not md_files:
                raise Exception(f"No markdown file found in MinerUClient output at {extracted_content_path}")

            md_file_path = md_files[0] # Assuming one MD file per doc

            layout_pdf_files = list(extracted_content_path.glob("*_layout.pdf"))
            layout_pdf_path_or_none = str(layout_pdf_files[0]) if layout_pdf_files else None

            return str(extracted_content_path), md_file_path.stem, layout_pdf_path_or_none
        else:
            error_msg = first_result.get("error_message", "Unknown error from MinerUClient")
            logger.error(f"MinerUClient processing failed for {doc_path}: {error_msg}")
            raise Exception(f"MinerU API error: {error_msg}")

    except Exception as e:
        logger.exception(f"Error during document processing via client for {doc_path}")
        raise gr.Error(f"Processing Error: {str(e)}") from e


def compress_directory_to_zip(directory_path_str: str, output_zip_path_str: str) -> int:
    directory_path = Path(directory_path_str)
    output_zip_path = Path(output_zip_path_str)
    try:
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in directory_path.rglob('*'):
                if item.is_file():
                    arcname = item.relative_to(directory_path)
                    zipf.write(item, arcname)
        logger.info(f"Successfully compressed {directory_path} to {output_zip_path}")
        return 0
    except Exception as e:
        logger.exception(f"Failed to compress directory {directory_path}: {e}")
        return -1

def image_to_base64(image_path: Path) -> str:
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def replace_images_with_base64_in_markdown(markdown_text: str, image_base_dir_str: str) -> str:
    image_base_dir = Path(image_base_dir_str)
    pattern = r'\!\[([^\]]*)\]\(([^)]+)\)'

    def replacer(match: re.Match) -> str:
        alt_text = match.group(1)
        original_image_path_in_md = match.group(2)

        if original_image_path_in_md.startswith('data:'):
            return match.group(0)

        cleaned_image_path = original_image_path_in_md.lstrip('./')
        full_image_path = image_base_dir / cleaned_image_path

        if full_image_path.exists() and full_image_path.is_file():
            try:
                base64_data = image_to_base64(full_image_path)
                ext = full_image_path.suffix.lower()
                mime_type_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
                mime_type = mime_type_map.get(ext, "application/octet-stream")
                if mime_type == "application/octet-stream" and ext not in ['.md', '.txt', '.pdf']:
                     logger.warning(f"Unknown image MIME type for extension {ext} at {full_image_path}, using application/octet-stream.")

                return f'![{alt_text}](data:{mime_type};base64,{base64_data})'
            except Exception as e:
                logger.error(f"Error converting image {full_image_path} to base64: {e}")
        else:
            logger.warning(f"Image not found: {full_image_path} (referenced as '{original_image_path_in_md}' in Markdown from base '{image_base_dir}')")
        return match.group(0)

    return re.sub(pattern, replacer, markdown_text)

async def main_conversion_flow(
    gradio_file_obj: Optional[Any],
    max_pages: int,
    is_ocr: bool,
    formula_enable: bool,
    table_enable: bool,
    language: str,
    progress: gr.Progress
) -> Tuple[str, str, Optional[str], Optional[str]]:
    if gradio_file_obj is None:
        # This case should ideally be prevented by Gradio UI if file input is mandatory.
        logger.warning("Conversion called without a file object.")
        return "Error: No file provided.", "", None, None

    uploaded_file_path = Path(gradio_file_obj.name)
    logger.info(f"Processing uploaded file: {uploaded_file_path}. UI Params: Max pages: {max_pages}, OCR: {is_ocr}, Lang: {language}")

    progress(0, desc="Preparing input file...")
    prepared_input_file_path = await copy_file_to_app_temp(uploaded_file_path, "inputs")
    if not prepared_input_file_path:
        logger.error(f"Failed to prepare input file from {uploaded_file_path}.")
        return "Error: Could not prepare input file.", "", None, None

    run_timestamp = time.strftime("%y%m%d_%H%M%S")
    run_id = f'{prepared_input_file_path.stem}_{run_timestamp}_{str_sha256(str(time.time()))[:6]}'
    current_run_artifacts_dir = APP_TEMP_DIR / "gradio_conversion_runs" / run_id
    current_run_artifacts_dir.mkdir(exist_ok=True, parents=True)
    logger.info(f"Artifacts for this run will be stored in: {current_run_artifacts_dir}")

    client_output_target_dir = current_run_artifacts_dir / "client_raw_output" # Where client places batch_id folder
    client_output_target_dir.mkdir(exist_ok=True, parents=True)

    progress(0.1, desc="Starting document conversion via MinerU API...")
    try:
        content_dir_from_client_str, md_file_stem_from_client, layout_pdf_path_from_client_str = await parse_document_via_client(
            prepared_input_file_path, client_output_target_dir, max_pages, is_ocr, language
        )
        progress(0.7, desc="Conversion complete. Packaging results...")

        content_dir_from_client = Path(content_dir_from_client_str)
        markdown_file_path = content_dir_from_client / f"{md_file_stem_from_client}.md"

        if not markdown_file_path.exists():
            logger.error(f"Critical: Markdown file expected at {markdown_file_path} not found.")
            raise gr.Error("Conversion process anomaly: Markdown file is missing.")

        raw_markdown_text = markdown_file_path.read_text(encoding='utf-8')
        markdown_for_display = replace_images_with_base64_in_markdown(raw_markdown_text, content_dir_from_client_str)

        zip_file_name = f"{prepared_input_file_path.stem}_parsed_output.zip"
        zip_file_path = current_run_artifacts_dir / zip_file_name

        zip_creation_status = compress_directory_to_zip(content_dir_from_client_str, str(zip_file_path))
        zip_file_path_for_gradio = str(zip_file_path) if zip_creation_status == 0 else None
        if zip_creation_status != 0: logger.error(f'Failed to compress {content_dir_from_client_str}.')
        else: logger.info(f'Successfully compressed results to {zip_file_path_for_gradio}')

        preview_pdf_path_for_gradio: Optional[str] = None
        if layout_pdf_path_from_client_str and Path(layout_pdf_path_from_client_str).exists():
            final_layout_pdf_path = current_run_artifacts_dir / Path(layout_pdf_path_from_client_str).name
            shutil.copy(layout_pdf_path_from_client_str, final_layout_pdf_path)
            preview_pdf_path_for_gradio = str(final_layout_pdf_path)
        elif prepared_input_file_path.suffix.lower() == ".pdf":
            preview_pdf_path_for_gradio = str(prepared_input_file_path)

        progress(1, desc="All done!")
        return markdown_for_display, raw_markdown_text, zip_file_path_for_gradio, preview_pdf_path_for_gradio

    except Exception as e:
        logger.exception("Error in main_conversion_flow")
        return f"## Conversion Error\n\n```\n{str(e)}\n```", "", None, None


latex_delimiters_config = [
    {'left': '$$', 'right': '$$', 'display': True}, {'left': '$', 'right': '$', 'display': False},
    {'left': '\\(', 'right': '\\)', 'display': False}, {'left': '\\[', 'right': '\\]', 'display': True},
]

try:
    header_html_path = Path(__file__).resolve().parent / 'header.html'
    app_header_html = header_html_path.read_text() if header_html_path.exists() else ""
    if not app_header_html: logger.warning(f"{header_html_path} not found or empty.")
except Exception as e:
    logger.error(f"Error loading header.html: {e}")
    app_header_html = ""

latin_lang_list = ['af', 'az', 'bs', 'cs', 'cy', 'da', 'de', 'es', 'et', 'fr', 'ga', 'hr', 'hu', 'id', 'is', 'it', 'ku', 'la', 'lt', 'lv', 'mi', 'ms', 'mt', 'nl', 'no', 'oc', 'pi', 'pl', 'pt', 'ro', 'rs_latin', 'sk', 'sl', 'sq', 'sv', 'sw', 'tl', 'tr', 'uz', 'vi', 'french', 'german']
arabic_lang_list = ['ar', 'fa', 'ug', 'ur']
cyrillic_lang_list = ['ru', 'rs_cyrillic', 'be', 'bg', 'uk', 'mn', 'abq', 'ady', 'kbd', 'ava', 'dar', 'inh', 'che', 'lbe', 'lez', 'tab']
devanagari_lang_list = ['hi', 'mr', 'ne', 'bh', 'mai', 'ang', 'bho', 'mah', 'sck', 'new', 'gom', 'sa', 'bgc']
other_lang_list = ['ch', 'ch_lite', 'ch_server', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka']
additional_lang_groups = ['latin', 'arabic', 'cyrillic', 'devanagari']
available_languages = sorted(list(set(other_lang_list + latin_lang_list + arabic_lang_list + cyrillic_lang_list + devanagari_lang_list + additional_lang_groups)))


def safe_filename_stem(input_path: Path) -> str:
    return re.sub(r'[^\w.-]', '_', Path(input_path).stem) # Allow dots in stem

async def copy_file_to_app_temp(original_file_path: Path, purpose_subdir: str = "uploads") -> Optional[Path]:
    try:
        target_temp_dir = APP_TEMP_DIR / purpose_subdir
        target_temp_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%y%m%d%H%M%S")
        # Use original file suffix for the temp file
        suffix = original_file_path.suffix
        # Create a more unique stem using hash of path and time
        unique_stem = f"{timestamp}_{safe_filename_stem(original_file_path)}_{str_sha256(str(original_file_path) + str(time.time()))[:8]}"
        temp_file_name = unique_stem + suffix
        destination_path = target_temp_dir / temp_file_name

        shutil.copy(original_file_path, destination_path)
        logger.info(f"Copied input file '{original_file_path}' to app temp: '{destination_path}'")
        return destination_path
    except Exception as e:
        logger.exception(f"Failed to copy file {original_file_path} to app temporary directory.")
        return None

if __name__ == '__main__':
    try:
        for old_app_temp_dir in Path(tempfile.gettempdir()).glob("mineru_gradio_app_*"):
            if old_app_temp_dir.is_dir() and old_app_temp_dir != APP_TEMP_DIR:
                logger.warning(f"Attempting to clean up old app temp directory: {old_app_temp_dir}")
                shutil.rmtree(old_app_temp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"Error during cleanup of old temp directories: {e}")

    with gr.Blocks(title="MinerU Document Parser", theme=gr.themes.Soft()) as demo:
        if app_header_html: gr.HTML(app_header_html)

        with gr.Row():
            with gr.Column(variant='panel', scale=5):
                gr.Markdown("## 📤 Upload Document")
                ui_file_input = gr.File(label='PDF or Image File', file_types=['.pdf', '.png', '.jpeg', '.jpg', '.bmp', '.tiff'])

                gr.Markdown("### ⚙️ Conversion Settings")
                with gr.Row(equal_height=True):
                    ui_max_pages_slider = gr.Slider(minimum=0, maximum=200, value=20, step=1, label='Max Pages to Convert', info="Set to 0 to process all pages.")
                    ui_language_dropdown = gr.Dropdown(available_languages, label='Document Language', value='ch')

                ui_ocr_checkbox = gr.Checkbox(label='Force Enable OCR', value=False, info="Enable for scanned documents or images.")
                # Formula and table are not passed to client currently, so hide them to avoid confusion.
                # ui_formula_checkbox = gr.Checkbox(label='Formula Recognition', value=True, visible=False)
                # ui_table_checkbox = gr.Checkbox(label='Table Recognition', value=True, visible=False)

                with gr.Row():
                    ui_convert_button = gr.Button('Convert Document', variant='primary', elem_id="convert_button_elem")
                    ui_clear_button = gr.ClearButton(value='Clear All Fields')

                gr.Markdown("### 📄 Document Preview")
                ui_pdf_preview = PDF(label='Preview Pane', interactive=False, visible=True, height=650)

                examples_dir = Path(__file__).resolve().parent / 'examples'
                example_file_paths = []
                if examples_dir.exists() and examples_dir.is_dir():
                    example_file_paths = sorted([str(f) for f in examples_dir.glob('*.pdf')]) # Sort for consistency

                if example_file_paths:
                    with gr.Accordion('Show Examples', open=False):
                        gr.Examples(examples=example_file_paths, inputs=ui_file_input, label="Click an example to load it")
                else: gr.Markdown("_(No examples found in ./examples directory)_")

            with gr.Column(variant='panel', scale=5):
                gr.Markdown("## 📜 Conversion Results")
                ui_zip_output_file = gr.File(label='Download Full Results (ZIP archive)', interactive=False)

                with gr.Tabs():
                    with gr.Tab('Formatted Markdown Output'):
                        ui_markdown_display = gr.Markdown(label='Rendered Markdown with Embedded Images', height=1000,show_copy_button=True, latex_delimiters=latex_delimiters_config, line_breaks=True)
                    with gr.Tab('Raw Markdown Text'):
                        ui_markdown_text_raw = gr.TextArea(lines=40, label="Plain Markdown Text", show_copy_button=True)

        async def handle_file_upload_for_preview(gradio_file_obj: Optional[Any]) -> Optional[str]:
            if gradio_file_obj:
                uploaded_file_path = Path(gradio_file_obj.name)
                previewable_path = await copy_file_to_app_temp(uploaded_file_path, "previews")
                return str(previewable_path) if previewable_path else None
            return None

        ui_file_input.change(fn=handle_file_upload_for_preview, inputs=ui_file_input, outputs=ui_pdf_preview, show_progress="hidden")

        # Hidden dummy inputs for formula/table to match main_conversion_flow signature
        # These will be removed if formula/table are not supported by the client.
        dummy_formula = gr.Checkbox(value=True, visible=False)
        dummy_table = gr.Checkbox(value=True, visible=False)

        ui_convert_button.click(
            fn=main_conversion_flow,
            inputs=[ui_file_input, ui_max_pages_slider, ui_ocr_checkbox, dummy_formula, dummy_table, ui_language_dropdown],
            outputs=[ui_markdown_display, ui_markdown_text_raw, ui_zip_output_file, ui_pdf_preview]
        )

        components_to_clear = [ui_file_input, ui_markdown_display, ui_markdown_text_raw, ui_zip_output_file, ui_pdf_preview]
        def reset_settings_controls_js_action(): # Returns JS to reset specific controls
             # For Gradio versions that support JS actions for ClearButton this is cleaner.
             # If not, lambda returning tuple of default values is needed.
            return False, 0, 'ch' # ocr, max_pages, lang (slider value 0 for "all pages")

        # ClearButton can take a list of components.
        # To reset specific input controls to defaults, we use .then() with a function.
        ui_clear_button.add(components_to_clear).then(
            fn=lambda: (False, 0, 'ch'), # ocr_checkbox, max_pages_slider, language_dropdown
            inputs=[],
            outputs=[ui_ocr_checkbox, ui_max_pages_slider, ui_language_dropdown]
        )

    logger.info("Starting Gradio demo...")
    demo.queue().launch(server_name='0.0.0.0', server_port=7860, debug=True, show_error=True)
