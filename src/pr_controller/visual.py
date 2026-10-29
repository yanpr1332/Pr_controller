"""Optional bitmap preparation; imported only when called (pip install .[visual])."""
from pathlib import Path

def photo_card(source, destination, *, border=14, padding=60, shadow_blur=18):
    from PIL import Image, ImageOps, ImageDraw, ImageFilter
    if min(border, padding, shadow_blur) < 0:
        raise ValueError('Invalid card dimensions')
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    with Image.open(source) as source_image:
        image = ImageOps.exif_transpose(source_image).convert('RGB')
    image.thumbnail((2200, 1800), Image.Resampling.LANCZOS)
    w, h = image.size
    result = Image.new('RGBA', (w + 2 * (padding + border), h + 2 * (padding + border)))
    ImageDraw.Draw(result).rectangle((padding + 6, padding + 12, padding + w + 2 * border + 6, padding + h + 2 * border + 12), fill=(20, 30, 25, 75))
    result = result.filter(ImageFilter.GaussianBlur(shadow_blur))
    ImageDraw.Draw(result).rectangle((padding, padding, padding + w + 2 * border, padding + h + 2 * border), fill='white')
    result.paste(image, (padding + border, padding + border))
    destination.parent.mkdir(parents=True, exist_ok=True)
    result.save(destination)
    return {'item': str(destination.resolve()), 'width': result.width, 'height': result.height}

def pdf_pages(source, pages, destination, *, scale=2):
    import pypdfium2 as pdfium
    if scale <= 0 or not pages:
        raise ValueError('Positive scale and nonempty pages required')
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    document = pdfium.PdfDocument(str(source))
    try:
        if any((p < 1 or p > len(document) for p in pages)):
            raise ValueError('Page out of range')
        destination.mkdir(parents=True)
        out = []
        for number in pages:
            page = document[number - 1]
            try:
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    path = destination / f'page_{number:03}.png'
                    image.save(path)
                    out.append({'item': str(path.resolve()), 'width': image.width, 'height': image.height, 'page': number})
                finally:
                    bitmap.close()
            finally:
                page.close()
        return out
    finally:
        document.close()
