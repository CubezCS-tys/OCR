# QUICK IMPLEMENTATION GUIDE
# How to add temperature=0.0 for maximum consistency

## Step 1: Modify generation config in main.py

### Location: Line 1142-1150 in backend/main.py

### BEFORE:
```python
# Build generation config with optional seed for deterministic outputs
config = {}
if seed is not None:
    config['seed'] = seed

response = client.models.generate_content(
    model=requested_model,
    contents=[system_prompt, uploaded_file],
    config=config if config else None,
```

### AFTER (add temperature):
```python
# Build generation config with optional seed for deterministic outputs
config = {
    'temperature': 0.0,  # ← ADD THIS for maximum consistency
}
if seed is not None:
    config['seed'] = seed

response = client.models.generate_content(
    model=requested_model,
    contents=[system_prompt, uploaded_file],
    config=config,  # ← Remove the "if config else None" check
```

## Step 2: Do the same for the second location (whole-document mode)

### Location: Line 1361-1369 in backend/main.py

### BEFORE:
```python
# Build generation config with optional seed for deterministic outputs
config = {}
if seed is not None:
    config['seed'] = seed

response = client.models.generate_content(
    model=requested_model,
    contents=[system_prompt, {"mime_type": "application/pdf", "data": pdf_data}],
    config=config if config else None,
```

### AFTER:
```python
# Build generation config with optional seed for deterministic outputs
config = {
    'temperature': 0.0,  # ← ADD THIS
}
if seed is not None:
    config['seed'] = seed

response = client.models.generate_content(
    model=requested_model,
    contents=[system_prompt, {"mime_type": "application/pdf", "data": pdf_data}],
    config=config,  # ← Remove the "if config else None" check
```

## Step 3: Test the changes

```bash
# Run with seed for reproducibility
python backend/main.py --seed 42 input_pdfs/test.pdf output_html/ --per-page

# Test consistency (run multiple times)
python test_consistency.py input_pdfs/test.pdf 3 42
```

## Expected Results

With temperature=0.0 + seed=42:
- ✅ Same input → IDENTICAL output (character-for-character)
- ✅ 99-100% consistency across runs
- ✅ Deterministic behavior

Without temperature=0.0 (only seed):
- ⚠️ High consistency but may have minor variations
- ⚠️ ~95-98% consistency

## Complete Reproducibility Stack

1. ✅ **Temperature = 0.0** (add this)
2. ✅ **Seed parameter** (already implemented)
3. ✅ **Enhanced prompt** (copy from enhanced_prompt.py)
4. ✅ **Template-based CSS** (already in prompt)
5. ✅ **Validation checklist** (in enhanced prompt)

## Alternative: Quick Test Without Modifying main.py

If you want to test before modifying main.py, you can check if Gemini API supports temperature in config:

```python
# Test in Python console
import google.generativeai as genai

genai.configure(api_key="YOUR_KEY")
model = genai.GenerativeModel("gemini-2.5-flash")

# Test with temperature
response = model.generate_content(
    "Say exactly: Hello World",
    generation_config={
        'temperature': 0.0,
        'seed': 42
    }
)
print(response.text)
```

## Troubleshooting

### Issue: "temperature" parameter not recognized
**Solution**: Check Gemini API version. Some versions use:
```python
config = {
    'candidate_count': 1,
    'temperature': 0.0,
    'top_p': 1.0,
    'top_k': 1,
}
```

### Issue: Still seeing variations
**Check**:
1. Seed is actually being passed (add print statement)
2. Temperature is set to 0.0 (add print statement)
3. Prompt is deterministic (no timestamps, no random IDs)
4. Input images are identical (same resolution, compression)

### Issue: Temperature makes output worse
**Solution**: Temperature=0.0 means "always pick most likely token"
- Good for: Reproducibility, consistency, structured output
- May reduce: Creativity, natural variation
- For OCR: This is EXACTLY what you want!
