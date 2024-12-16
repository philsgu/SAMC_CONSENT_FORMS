import fitz  # PyMuPDF

# Load the PDF
pdf_path = "case_study_consent.pdf"
doc = fitz.open(pdf_path)

# Initialize a list to hold the results
fields_coordinates = []

# Define keywords for identifying fields
keywords = [
    "Patient Name:", "DOB:", "Address:", "City:", "State:", "Email:", "Phone:", "focus on","Signature of Patient", "Date", "Description of Authority", "Verbal Authority", "Name of Saint Agnes Medical"
]

# Loop through all the pages in the PDF
for page_num in range(len(doc)):
    page = doc[page_num]
    
    # Search for the keywords
    for keyword in keywords:
        results = page.search_for(keyword)
        for rect in results:
            # Adjusting the rectangle to cover the underline area (assume ~200 units for underline length)
            underline_rect = fitz.Rect(rect.x1, rect.y0, rect.x1 + 200, rect.y1)
            fields_coordinates.append({
                "field": keyword,
                "page": page_num + 1,
                "coordinates": {
                    "x0": underline_rect.x0,
                    "y0": underline_rect.y0,
                    "x1": underline_rect.x1,
                    "y1": underline_rect.y1,
                }
            })

# Print the results
for field in fields_coordinates:
    print(f"Field: {field['field']}, Page: {field['page']}, Coordinates: {field['coordinates']}")