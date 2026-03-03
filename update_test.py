with open("tests/unit/storage/test_bagofholding_file.py", "r") as f:
    content = f.read()

content = content.replace("with pytest.raises(OSError):", "with pytest.raises(KeyError):")

with open("tests/unit/storage/test_bagofholding_file.py", "w") as f:
    f.write(content)
