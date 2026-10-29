import importlib.util,tempfile,unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('pypdfium2') and importlib.util.find_spec('PIL'),'Install visual extras')
class PdfTests(unittest.TestCase):
    def test_render_generated_pdf_without_changing_source(self):
        from pr_controller.visual import pdf_pages
        stream=b'BT /F1 12 Tf 20 260 Td (Synthetic test page) Tj ET\n'
        objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
        document=bytearray(b'%PDF-1.4\n');offsets=[0]
        for i,obj in enumerate(objects,1):offsets.append(len(document));document.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
        xref=len(document);document.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
        for offset in offsets[1:]:document.extend(f'{offset:010} 00000 n \n'.encode())
        document.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.pdf';source.write_bytes(document)
            pages=pdf_pages(source,[1],root/'pages',scale=2)
            self.assertEqual((pages[0]['width'],pages[0]['height']),(400,600))
            self.assertEqual(source.read_bytes(),document)
            with self.assertRaises(FileExistsError):pdf_pages(source,[1],root/'pages')

if __name__=='__main__':unittest.main()
