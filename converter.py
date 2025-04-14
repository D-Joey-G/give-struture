import streamlit as st
import json
import pandas as pd
import xml.dom.minidom
import xml.etree.ElementTree as ET
import anthropic

st.set_page_config(
    page_title="Text to Structured Output Converter",
    page_icon="🔄",
    layout="wide"
)

# Define template schemas
TEMPLATES = {
    "contact": {
        "label": "Contact Information",
        "example": "Edward Casaubon, Priest at Middlemarch. Email: key2myth@lowick.com, Phone: 07 777 777 777",
        "schema": """{
  "name": "String - The person's full name",
  "jobTitle": "String - Their professional title",
  "company": "String - Organization or company name",
  "email": "String - Email address",
  "phone": "String - Phone number with any formatting"
}"""
    },
    "event": {
        "label": "Event Details",
        "example": "Team pub trip on Tuesday, 8th of April at 8pm. Taking place at The King and Queen. Celebrating the big project ship!",
        "schema": """{
  "eventName": "String - Name or title of the event",
  "date": "String - Date of the event",
  "day": "String - Day of the week",
  "time": "String - Time of the event",
  "location": "String - Where the event takes place",
  "description": "String - Any additional details about the event (if provided)"
}"""
    },
    "address": {
        "label": "Address",
        "example": "10 Avenue Road, Flat 10, London, NW3 1FE",
        "schema": """{
  "street": "String - Street number and name",
  "flat": "String - Flat number/letter, if given",
  "city": "String - City name",
  "region": "String - Count, state, province, or region",
  "postCode": "String - Post or zip code",
  "country": "String - Country (if provided)"
}"""
    },
    "product": {
        "label": "Product Listing",
        "example": "Apple iPhone 13 Pro, 256GB, £699, Color: Graphite, In Stock",
        "schema": """{
  "productName": "String - Full product name",
  "brand": "String - Brand or manufacturer",
  "model": "String - Model name or number",
  "specs": "Object - Technical specifications as key-value pairs",
  "price": "String - Price with currency symbol",
  "color": "String - Color variant",
  "availability": "String - Stock or availability status"
}"""
    },
    "recipe": {
        "label": "Recipe",
        "example": "Chocolate Chip Cookies: 2 cups flour, 1 cup sugar, 1/2 cup butter, 2 eggs, 1 tsp vanilla, 1 cup chocolate chips. Bake at 350°F for 12 minutes.",
        "schema": """{
  "recipeName": "String - Name of the dish",
  "ingredients": "Array - List of ingredients with quantities",
  "instructions": "String or Array - Cooking steps",
  "cookingTime": "String - Total time needed",
  "temperature": "String - Cooking temperature (if applicable)",
  "servings": "Number - Number of servings (if provided)"
}"""
    },
    "custom": {
        "label": "Custom (Specify Schema)",
        "example": "Enter any text and specify the schema you want to extract",
        "schema": """{
  "key1": "String - Description",
  "key2": "String - Description",
  "key3": "String - Description"
}"""
    }
}

def format_json_output(data):
    """Format Python object (dict/list) as a nice JSON string"""
    return json.dumps(data, indent=2)
    

def format_xml_output(xml_str):
    """Format XML string to be more readable"""
    try:
        dom = xml.dom.minidom.parseString(xml_str)
        return dom.toprettyxml()
    except xml.parsers.expat.ExpatError:
        return xml_str

def convert_json_to_csv(data):
    """Convert Python object (dict) to CSV format"""
    try:
        # Handle nested structures by flattening first level
        flattened_data = {}
        # Ensure data is a dictionary before iterating
        if not isinstance(data, dict):
             return f"Error converting to CSV: Input data is not a dictionary (got {type(data)})."
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                flattened_data[key] = json.dumps(value)
            else:
                flattened_data[key] = value

        # Convert to DataFrame and then to CSV
        df = pd.DataFrame([flattened_data])
        return df.to_csv(index=False)
    except Exception as e:
        return f"Error converting to CSV: {str(e)}"

def convert_json_to_xml(data):
    """Convert Python object (dict) to XML format"""
    try:
        # Create root element
        root = ET.Element("root")

        # Ensure data is a dictionary before iterating
        if not isinstance(data, dict):
            return f"Error converting to XML: Input data is not a dictionary (got {type(data)})."

        # Add each key-value pair as a child element
        for key, value in data.items():
            child = ET.SubElement(root, key)
            
            if isinstance(value, list):
                # Handle lists
                for item in value:
                    item_elem = ET.SubElement(child, "item")
                    if isinstance(item, dict):
                        for k, v in item.items():
                            sub_elem = ET.SubElement(item_elem, k)
                            sub_elem.text = str(v)
                    else:
                        item_elem.text = str(item)
            elif isinstance(value, dict):
                # Handle dictionaries
                for k, v in value.items():
                    sub_elem = ET.SubElement(child, k)
                    sub_elem.text = str(v)
            else:
                # Handle simple values
                child.text = str(value)
                
        # Convert to string
        rough_string = ET.tostring(root, 'utf-8')
        return format_xml_output(rough_string)
    except Exception as e:
        return f"Error converting to XML: {str(e)}"

def extract_json_from_claude_response(response_text):
    """Extract JSON from Claude's response"""
    # First try to find JSON blocks
    import re
    json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    match = re.search(json_pattern, response_text)
    
    if match:
        return match.group(1).strip()
    
    # If no code blocks, try to find JSON objects
    json_pattern = r'({[\s\S]*})'
    match = re.search(json_pattern, response_text)
    
    if match:
        return match.group(1).strip()
    
    # If all else fails, return the original text
    return response_text

def process_text_with_claude(text_input, schema, output_format):
    """Process text using Claude API"""
    # Get API key from Streamlit secrets
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
        client = anthropic.Anthropic(api_key=api_key)
    except KeyError:
        return "Error: API key not configured. Please check the documentation for setup instructions."
        
    # Prepare the prompt
    prompt = f"""
Parse the following unstructured text and convert it to a structured JSON object.
Use this schema as a guide:
{schema}

TEXT TO PARSE:
```
{text_input}
```

First, analyze the text to identify key information that matches the schema.
Then, output ONLY a valid JSON object wrapped in triple backticks with the json label. Do not include any other text or explanation before or after the JSON block.
"""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=4000,
            temperature=0,
            system="You extract structured data from unstructured text based on provided schemas. Output only the extracted data in valid JSON format wrapped in ```json ... ``` with no additional text.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract the response content
        raw_output = response.content[0].text if response.content else ""

        # Always extract JSON first
        json_output_str = extract_json_from_claude_response(raw_output)

        # Validate JSON
        try:
            parsed_json_data = json.loads(json_output_str)
        except json.JSONDecodeError as e:
            return f"Error: Claude returned invalid JSON. {str(e)}\nRaw output:\n{raw_output}"

        # Process based on the desired output format
        if output_format == "json":
            return format_json_output(parsed_json_data) # Use the original string for formatting
        elif output_format == "csv":
            # Pass the validated JSON string to the conversion function
            return convert_json_to_csv(parsed_json_data)
        elif output_format == "xml":
            # Pass the validated JSON string to the conversion function
            return convert_json_to_xml(parsed_json_data)
        else:
            # Should not happen with current options, but return raw if needed
            return json.dumps(parsed_json_data, indent=2)

    except Exception as e:
        return f"Error processing with Claude: {str(e)}"

def check_api_key_configured():
    """Safely check if API key is configured without exposing it"""
    try:
        _ = st.secrets["ANTHROPIC_API_KEY"]
        return True
    except KeyError:
        return False

def main():
    st.title("Text to Structured Output Converter")
    st.write("Convert unstructured text to structured formats using Claude AI")
    
    # Create sidebar for settings
    with st.sidebar:
        st.header("Settings")
        
        # Check if API key exists in secrets
        try:
            _ = st.secrets["ANTHROPIC_API_KEY"]  # Only check existence, don't store or display
            st.success("✅ Claude API key found")
        except KeyError:
            st.error("❌ Claude API key not found. Please add it to your secrets.toml file")
            st.info("Your secrets.toml file should include: ANTHROPIC_API_KEY=your_key_here in .streamlit/secrets.toml")
        
        st.subheader("Output Format")
        output_format = st.selectbox(
            "Select output format",
            options=["json", "csv", "xml"],
            index=0
        )
        
    # Main content area
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Input")
        
        # Template selection
        template_options = {t["label"]: k for k, t in TEMPLATES.items()}
        selected_template_label = st.selectbox(
            "Template",
            options=list(template_options.keys()),
            index=0
        )
        selected_template = template_options[selected_template_label]
        
        # Load example button
        if st.button("Load Example"):
            st.session_state.text_input = TEMPLATES[selected_template]["example"]
            st.session_state.schema = TEMPLATES[selected_template]["schema"]
        
        # Initialize session state for text input
        if "text_input" not in st.session_state:
            st.session_state.text_input = ""
        if "schema" not in st.session_state:
            st.session_state.schema = TEMPLATES[selected_template]["schema"]
            
        # Text input area
        text_input = st.text_area(
            "Enter your text to convert",
            height=200,
            value=st.session_state.text_input
        )
        st.session_state.text_input = text_input
        
        # Schema input
        schema = st.text_area(
            "Schema (JSON format)",
            height=200,
            value=st.session_state.schema,
            help="Define the structure you want to extract"
        )
        st.session_state.schema = schema
        
        # Process button
        process_button = st.button("Convert with Claude", type="primary")
        
    with col2:
        st.subheader("Output")
        
        # Initialize output in session state
        if "output" not in st.session_state:
            st.session_state.output = ""
            
        # Process the text if button is clicked
        if process_button:
            if not text_input:
                st.error("Please enter some text to convert")
            else:
                if check_api_key_configured():
                    with st.spinner("Processing with Claude..."):
                        result = process_text_with_claude(
                            text_input,
                            schema,
                            output_format
                        )
                        st.session_state.output = result
                else:
                    st.error("Claude API key not found in Streamlit secrets")
                    
        # Output display area
        st.text_area(
            f"Converted {output_format.upper()} Output",
            value=st.session_state.output,
            height=450
        )
        
        # Download button (if there's output)
        if st.session_state.output:
            # Determine file extension based on format
            file_extension = output_format
            
            output_bytes = st.session_state.output.encode()
            st.download_button(
                label=f"Download as .{file_extension}",
                data=output_bytes,
                file_name=f"converted_data.{file_extension}",
                mime=f"text/{file_extension}"
            )
    
    # Footer with instructions
    st.divider()
    with st.expander("How to use this tool"):
        st.write("""
        ### How to use this converter:
        
        1. **Ensure your Claude API key is set** in your secrets.toml file
        2. **Select a template** for the type of data you want to extract
        3. **Enter your text** in the input box or load an example
        4. **Review the schema** and modify if needed
        5. **Click "Convert with Claude"** to process your text
        6. **Download the result** in your preferred format
        
        ### About Schemas:
        
        The schema tells Claude what information to extract from your text and how to structure it.
        
        A basic schema looks like:
        ```json
        {
          "fieldName": "Data type - Description of what to extract",
          "anotherField": "Data type - Description"
        }
        ```
        
        You can specify nested structures, arrays, and provide examples in your schema to guide the extraction.
        """)

if __name__ == "__main__":
    main()
