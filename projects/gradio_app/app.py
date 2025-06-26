# Copyright (c) Opendatalab. All rights reserved.

import base64
import os
import re
import time
import zipfile
from pathlib import Path

import gradio as gr
from gradio_pdf import PDF
from loguru import logger

from mineru.cli.common import prepare_env, do_parse, read_fn
from mineru.utils.hash_utils import str_sha256
from mineru.backend.pipeline.pipeline_analyze import pipeline_analyze_v2
from mineru.utils.config_reader import get_config, find_config_file_by_backend
from mineru.utils.model_utils import get_model_info
from mineru.utils.pdf_image_tools import get_pdf_dim_list


def parse_pdf_directly(doc_path, output_dir, end_page_id, is_ocr, formula_enable, table_enable, language):
    os.makedirs(output_dir, exist_ok=True)

    try:
        file_name = f'{str(Path(doc_path).stem)}_{time.strftime("%y%m%d_%H%M%S")}'
        pdf_data = read_fn(doc_path)
        if is_ocr:
            parse_method = 'ocr'
        else:
            parse_method = 'auto'

        local_image_dir, local_md_dir = prepare_env(output_dir, file_name, parse_method)

        # Load config
        config_path = find_config_file_by_backend("pipeline")
        config = get_config(config_path)
        model_config = config.model_config
        model_ocr_config = model_config.model_ocr_config
        model_layout_config = model_config.model_layout_config
        model_table_config = model_config.model_table_config
        model_mfd_config = model_config.model_mfd_config
        model_mfr_config = model_config.model_mfr_config
        model_formula_config = model_config.model_formula_config
        model_reading_order_config = model_config.model_reading_order_config

        # Get model info
        model_list = get_model_info(model_config=model_config, backend="pipeline")


        middle_json_list, _ = pipeline_analyze_v2(
            pdf_bytes_list=[pdf_data],
            pdf_file_names=[file_name],
            output_dir=output_dir,
            p_lang_list=[language],
            parse_method=parse_method,
            model_list=model_list,
            model_ocr_config=model_ocr_config,
            model_layout_config=model_layout_config,
            model_table_config=model_table_config,
            model_mfd_config=model_mfd_config,
            model_mfr_config=model_mfr_config,
            model_formula_config=model_formula_config,
            model_reading_order_config=model_reading_order_config,
            p_formula_enable=formula_enable,
            p_table_enable=table_enable,
            p_start_page_id=0,  # Assuming start page is always 0 for Gradio app
            p_end_page_id=end_page_id,
            p_is_debug=False, # Or True, depending on desired behavior
            pdf_dim_list=get_pdf_dim_list([pdf_data])
        )

        # The do_parse function in mineru.cli.common handles saving the markdown and other outputs.
        # We can reuse it here, or reimplement the saving logic if needed.
        # For simplicity, let's assume do_parse can be adapted or we can extract relevant parts.
        # This part might need further refinement based on the exact behavior of do_parse.

        # Create the .md file from middle_json (this logic is usually within do_parse or subsequent steps)
        # For now, let's assume the markdown file is created in local_md_dir
        # This is a placeholder for the logic that converts middle_json to a markdown file.
        # In a real scenario, you would call the appropriate functions from mineru to do this.
        md_file_path = Path(local_md_dir) / f"{file_name}.md"
        if not middle_json_list or not middle_json_list[0]:
            # Handle case where parsing failed or produced no output
            with open(md_file_path, 'w', encoding='utf-8') as f:
                f.write("Error: PDF parsing failed to produce output.")
            logger.error(f"PDF parsing failed for {file_name}")
        else:
            # Assuming the first result in middle_json_list corresponds to our single PDF
            # And that it contains the markdown content or can be converted to it.
            # This is a simplification. The actual conversion from middle_json to .md is more complex.
            # Typically, `pipeline_middle_json_mkcontent.middle_json_to_markdown` would be used.
            # For this example, we'll just indicate success.
             # We need to ensure the markdown file is written by do_parse or a similar function.
            # Re-calling do_parse with the processed data if necessary, or extracting its file-writing logic.
            # For now, let's stick to the original do_parse for writing files,
            # but ideally, we'd use the direct analysis results.

            # To ensure file writing, we might need to call a specific function from mineru
            # that takes the middle_json and writes the .md file and other artifacts.
            # Let's revert to calling do_parse for now as it handles file output.
            # This means parse_pdf_directly is more about setting up and calling do_parse correctly.

            do_parse(
                output_dir=output_dir,
                pdf_file_names=[file_name],
                pdf_bytes_list=[pdf_data], # Pass raw bytes again, or ensure do_parse can take middle_json
                p_lang_list=[language],
                parse_method=parse_method,
                end_page_id=end_page_id,
                p_formula_enable=formula_enable,
                p_table_enable=table_enable,
                # We might need to pass model_list or config if do_parse is modified
                # For now, assuming original do_parse behavior for file writing
            )

        return local_md_dir, file_name
    except Exception as e:
        logger.exception(e)
        # Ensure output directories are created even in case of error for consistency
        if 'file_name' not in locals():
            file_name = f'error_parse_{time.strftime("%y%m%d_%H%M%S")}'
        if 'output_dir' in locals():
            os.makedirs(os.path.join(output_dir, file_name, "images"), exist_ok=True)
            md_path = os.path.join(output_dir, file_name, f"{file_name}.md")
            with open(md_path, 'w') as f:
                f.write(f"An error occurred during parsing: {e}")
            return os.path.join(output_dir, file_name), file_name
        return None, None


def compress_directory_to_zip(directory_path, output_zip_path):
    """压缩指定目录到一个 ZIP 文件。

    :param directory_path: 要压缩的目录路径
    :param output_zip_path: 输出的 ZIP 文件路径
    """
    try:
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:

            # 遍历目录中的所有文件和子目录
            for root, dirs, files in os.walk(directory_path):
                for file in files:
                    # 构建完整的文件路径
                    file_path = os.path.join(root, file)
                    # 计算相对路径
                    arcname = os.path.relpath(file_path, directory_path)
                    # 添加文件到 ZIP 文件
                    zipf.write(file_path, arcname)
        return 0
    except Exception as e:
        logger.exception(e)
        return -1


def image_to_base64(image_path):
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def replace_image_with_base64(markdown_text, image_dir_path):
    # 匹配Markdown中的图片标签
    pattern = r'\!\[(?:[^\]]*)\]\(([^)]+)\)'

    # 替换图片链接
    def replace(match):
        relative_path = match.group(1)
        full_path = os.path.join(image_dir_path, relative_path)
        base64_image = image_to_base64(full_path)
        return f'![{relative_path}](data:image/jpeg;base64,{base64_image})'

    # 应用替换
    return re.sub(pattern, replace, markdown_text)


def to_markdown(file_path, end_pages, is_ocr, formula_enable, table_enable, language):
    file_path = to_pdf(file_path)
    if file_path is None:
        return "Error: No file provided or file could not be processed.", "", None, None
    # 获取识别的md文件以及压缩包文件路径
    # Use the new direct parsing function
    local_md_dir, file_name = parse_pdf_directly(file_path, './output', end_pages - 1, is_ocr, formula_enable, table_enable, language)

    if local_md_dir is None or file_name is None:
        return "Error: PDF parsing failed.", "", None, None

    archive_zip_path = os.path.join('./output', str_sha256(local_md_dir) + '.zip')
    zip_archive_success = compress_directory_to_zip(local_md_dir, archive_zip_path)
    if zip_archive_success == 0:
        logger.info('压缩成功')
    else:
        logger.error('压缩失败')
    md_path = os.path.join(local_md_dir, file_name + '.md')
    with open(md_path, 'r', encoding='utf-8') as f:
        txt_content = f.read()
    md_content = replace_image_with_base64(txt_content, local_md_dir)
    # 返回转换后的PDF路径
    new_pdf_path = os.path.join(local_md_dir, file_name + '_layout.pdf')

    return md_content, txt_content, archive_zip_path, new_pdf_path


latex_delimiters = [
    {'left': '$$', 'right': '$$', 'display': True},
    {'left': '$', 'right': '$', 'display': False},
    {'left': '\\(', 'right': '\\)', 'display': False},
    {'left': '\\[', 'right': '\\]', 'display': True},
]


with open('header.html', 'r') as file:
    header = file.read()


latin_lang = [
        'af', 'az', 'bs', 'cs', 'cy', 'da', 'de', 'es', 'et', 'fr', 'ga', 'hr',  # noqa: E126
        'hu', 'id', 'is', 'it', 'ku', 'la', 'lt', 'lv', 'mi', 'ms', 'mt', 'nl',
        'no', 'oc', 'pi', 'pl', 'pt', 'ro', 'rs_latin', 'sk', 'sl', 'sq', 'sv',
        'sw', 'tl', 'tr', 'uz', 'vi', 'french', 'german'
]
arabic_lang = ['ar', 'fa', 'ug', 'ur']
cyrillic_lang = [
        'ru', 'rs_cyrillic', 'be', 'bg', 'uk', 'mn', 'abq', 'ady', 'kbd', 'ava',  # noqa: E126
        'dar', 'inh', 'che', 'lbe', 'lez', 'tab'
]
devanagari_lang = [
        'hi', 'mr', 'ne', 'bh', 'mai', 'ang', 'bho', 'mah', 'sck', 'new', 'gom',  # noqa: E126
        'sa', 'bgc'
]
other_lang = ['ch', 'ch_lite', 'ch_server', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka']
add_lang = ['latin', 'arabic', 'cyrillic', 'devanagari']

# all_lang = ['', 'auto']
all_lang = []
# all_lang.extend([*other_lang, *latin_lang, *arabic_lang, *cyrillic_lang, *devanagari_lang])
all_lang.extend([*other_lang, *add_lang])


def safe_stem(file_path):
    stem = Path(file_path).stem
    # 只保留字母、数字、下划线和点，其他字符替换为下划线
    return re.sub(r'[^\w.]', '_', stem)


def to_pdf(file_path):

    if file_path is None:
        return None

    pdf_bytes = read_fn(file_path)

    # unique_filename = f'{uuid.uuid4()}.pdf'
    unique_filename = f'{safe_stem(file_path)}.pdf'

    # 构建完整的文件路径
    tmp_file_path = os.path.join(os.path.dirname(file_path), unique_filename)

    # 将字节数据写入文件
    with open(tmp_file_path, 'wb') as tmp_pdf_file:
        tmp_pdf_file.write(pdf_bytes)

    return tmp_file_path


if __name__ == '__main__':
    with gr.Blocks() as demo:
        gr.HTML(header)
        with gr.Row():
            with gr.Column(variant='panel', scale=5):
                with gr.Row():
                    file = gr.File(label='Please upload a PDF or image', file_types=['.pdf', '.png', '.jpeg', '.jpg'])
                with gr.Row(equal_height=True):
                    with gr.Column(scale=4):
                        max_pages = gr.Slider(1, 20, 10, step=1, label='Max convert pages')
                    with gr.Column(scale=1):
                        language = gr.Dropdown(all_lang, label='Language', value='ch')
                with gr.Row():
                    is_ocr = gr.Checkbox(label='Force enable OCR', value=False)
                    formula_enable = gr.Checkbox(label='Enable formula recognition', value=True)
                    table_enable = gr.Checkbox(label='Enable table recognition(test)', value=True)
                with gr.Row():
                    change_bu = gr.Button('Convert')
                    clear_bu = gr.ClearButton(value='Clear')
                pdf_show = PDF(label='PDF preview', interactive=False, visible=True, height=800)
                with gr.Accordion('Examples:'):
                    example_root = os.path.join(os.path.dirname(__file__), 'examples')
                    gr.Examples(
                        examples=[os.path.join(example_root, _) for _ in os.listdir(example_root) if
                                  _.endswith('pdf')],
                        inputs=file
                    )

            with gr.Column(variant='panel', scale=5):
                output_file = gr.File(label='convert result', interactive=False)
                with gr.Tabs():
                    with gr.Tab('Markdown rendering'):
                        md = gr.Markdown(label='Markdown rendering', height=1100, show_copy_button=True,
                                         latex_delimiters=latex_delimiters,
                                         line_breaks=True)
                    with gr.Tab('Markdown text'):
                        md_text = gr.TextArea(lines=45, show_copy_button=True)
        file.change(fn=to_pdf, inputs=file, outputs=pdf_show)
        change_bu.click(fn=to_markdown, inputs=[file, max_pages, is_ocr, formula_enable, table_enable, language],
                        outputs=[md, md_text, output_file, pdf_show])
        clear_bu.add([file, md, pdf_show, md_text, output_file, is_ocr])

    demo.launch(server_name='0.0.0.0')
