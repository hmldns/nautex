import re
from pathlib import Path
from typing import Optional, Tuple


class SectionManagedFileService:
    """Generic service for managing files with marked sections that can be safely updated."""
    
    def __init__(self, section_start_marker: str, section_end_marker: str):
        """Initialize with custom section markers."""
        self.section_start = section_start_marker
        self.section_end = section_end_marker
    
    def has_section(self, file_path: Path) -> bool:
        """Check if file contains the marked section."""
        if not file_path.exists():
            return False
            
        try:
            content = file_path.read_text(encoding='utf-8')
            return self.section_start in content and self.section_end in content
        except Exception:
            return False
    
    def find_section_boundaries(self, content: str) -> Optional[Tuple[int, int]]:
        """Find start and end positions of the marked section."""
        start_match = re.search(re.escape(self.section_start), content)
        end_match = re.search(re.escape(self.section_end), content)
        
        if start_match and end_match and end_match.start() > start_match.start():
            return start_match.start(), end_match.end()
        return None
    
    def read_file_or_default(self, file_path: Path, default_content: str) -> str:
        """Read file content or return default if file doesn't exist."""
        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return default_content
    
    def update_section(self, file_path: Path, section_content: str, default_content: str = "") -> bool:
        """
        Update or add marked section in file.
        Returns True if file was modified.
        """
        # Read existing content or use default
        content = self.read_file_or_default(file_path, default_content)
        
        # Prepare full section with markers
        full_section = f"{self.section_start}\n\n{section_content.strip()}\n\n{self.section_end}"
        
        # Find existing section boundaries
        section_bounds = self.find_section_boundaries(content)
        
        if section_bounds:
            # Replace existing section, preserving surrounding whitespace
            start, end = section_bounds
            # Check if there's already a newline before the section
            prefix = "\n" if start > 0 and content[start-1] != '\n' else ""
            # Check if there's already a newline after the section
            suffix = "\n" if end < len(content) and content[end] != '\n' else ""
            new_content = content[:start] + prefix + full_section + suffix + content[end:]
        else:
            # Append section at the end
            new_content = content.rstrip() + "\n\n" + full_section + "\n"
        
        # Ensure parent directory exists and write content
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(new_content, encoding='utf-8')
        
        return True
    
    def ensure_file_with_section(
        self, 
        file_path: Path, 
        section_content: str, 
        default_content: str = ""
    ) -> bool:
        """
        Ensure file exists and contains the marked section with correct content.
        Returns True if any changes were made.
        """
        # Check if file exists and has section
        if not file_path.exists():
            # File doesn't exist, create it with section
            self.update_section(file_path, section_content, default_content)
            return True
        
        # File exists, check if it has the section and if content matches
        content = file_path.read_text(encoding='utf-8')
        section_bounds = self.find_section_boundaries(content)
        
        if not section_bounds:
            # Section doesn't exist, add it
            self.update_section(file_path, section_content, default_content)
            return True
        
        # Extract current section content (without markers)
        start, end = section_bounds
        current_section = content[start:end]
        
        # Build expected section with markers for comparison (same format as update_section)
        expected_section = f"{self.section_start}\n\n{section_content.strip()}\n\n{self.section_end}"
        
        # Compare normalized content (strip extra whitespace for comparison)
        if current_section.strip() != expected_section.strip():
            # Content differs, update it
            self.update_section(file_path, section_content, default_content)
            return True
        
        return False


# Tests for the service
def test_section_managed_file_service():
    """Test cases for SectionManagedFileService."""
    import tempfile
    
    # Test markers
    start_marker = "<!-- TEST_START -->"
    end_marker = "<!-- TEST_END -->"
    service = SectionManagedFileService(start_marker, end_marker)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = Path(temp_dir) / "test.md"
        
        # Test 1: File doesn't exist - should create with section
        section_content = "# Test Section\nThis is test content."
        default_content = "# Default File\nDefault content here."
        
        result = service.ensure_file_with_section(test_file, section_content, default_content)
        assert result == True, "Should return True when file is created"
        assert test_file.exists(), "File should be created"
        
        content = test_file.read_text()
        assert start_marker in content, "Should contain start marker"
        assert end_marker in content, "Should contain end marker"
        assert "Test Section" in content, "Should contain section content"
        print("✓ Test 1 passed: File creation with section")
        
        # Test 2: File exists without section - should add section
        test_file2 = Path(temp_dir) / "test2.md"
        test_file2.write_text("# Existing File\nExisting content.")
        
        result = service.ensure_file_with_section(test_file2, section_content)
        assert result == True, "Should return True when section is added"
        
        content = test_file2.read_text()
        assert "Existing File" in content, "Should preserve existing content"
        assert start_marker in content, "Should add start marker"
        assert "Test Section" in content, "Should add section content"
        print("✓ Test 2 passed: Adding section to existing file")
        
        # Test 3: File exists with section - should not modify
        result = service.ensure_file_with_section(test_file2, section_content)
        assert result == False, "Should return False when no changes needed"
        print("✓ Test 3 passed: No modification when section exists")
        
        # Test 4: Update existing section
        new_section_content = "# Updated Section\nUpdated content."
        service.update_section(test_file2, new_section_content)
        
        content = test_file2.read_text()
        assert "Updated Section" in content, "Should contain updated content"
        assert "Test Section" not in content, "Should not contain old content"
        assert content.count(start_marker) == 1, "Should have only one start marker"
        print("✓ Test 4 passed: Section update")
        
        # Test 5: Section boundaries detection
        test_content = f"""# File Header
Some content
{start_marker}
# Section Content
{end_marker}
More content"""
        
        boundaries = service.find_section_boundaries(test_content)
        assert boundaries is not None, "Should find section boundaries"
        start_pos, end_pos = boundaries
        assert test_content[start_pos:end_pos].startswith(start_marker), "Start position should be correct"
        assert test_content[start_pos:end_pos].endswith(end_marker), "End position should be correct"
        print("✓ Test 5 passed: Section boundary detection")
        
        # Test 6: Content comparison and update
        test_file3 = Path(temp_dir) / "test3.md"
        old_section = "# Old Content\nOld text"
        new_section = "# New Content\nNew text"
        
        # Create file with old section
        service.ensure_file_with_section(test_file3, old_section, default_content)
        initial_content = test_file3.read_text()
        
        # Try with same content - should not update
        result = service.ensure_file_with_section(test_file3, old_section, default_content)
        assert result == False, "Should not update when content is the same"
        
        # Try with different content - should update
        result = service.ensure_file_with_section(test_file3, new_section, default_content)
        assert result == True, "Should update when content differs"
        
        updated_content = test_file3.read_text()
        assert "New Content" in updated_content, "Should contain new content"
        assert "Old Content" not in updated_content, "Should not contain old content"
        print("✓ Test 6 passed: Content comparison and update")
        
        print("All tests passed! ✅")


if __name__ == "__main__":
    test_section_managed_file_service()
