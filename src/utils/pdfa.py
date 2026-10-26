"""Makes the generated PDFs PDF/A-3 conformant (required for ZUGFeRD / Factur-X)."""
from functools import lru_cache
from io import BytesIO
from PIL import ImageCms
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, StreamObject, TextStringObject


@lru_cache(maxsize=1)
def _srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def add_output_intent(pdf: bytes) -> bytes:
    """Adds the sRGB OutputIntent PDF/A requires for device-dependent colours."""
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf)))
    root = writer._root_object
    if "/OutputIntents" in root:
        return pdf

    profile = StreamObject()
    profile.set_data(_srgb_profile())
    profile[NameObject("/N")] = NumberObject(3)
    intent = DictionaryObject({
        NameObject("/Type"): NameObject("/OutputIntent"),
        NameObject("/S"): NameObject("/GTS_PDFA1"),
        NameObject("/OutputConditionIdentifier"): TextStringObject("sRGB IEC61966-2.1"),
        NameObject("/Info"): TextStringObject("sRGB IEC61966-2.1"),
        NameObject("/DestOutputProfile"): writer._add_object(profile),
    })
    root[NameObject("/OutputIntents")] = ArrayObject([writer._add_object(intent)])

    writer.pdf_header = b"%PDF-1.7"
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
