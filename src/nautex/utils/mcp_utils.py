"""Utility functions for MCP configuration."""
import json
import logging
import tempfile
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Literal, Optional, Tuple

# Set up logging
logger = logging.getLogger(__name__)


class MCPConfigStatus(str, Enum):
    """Status of MCP configuration integration.

    Used to indicate the current state
    of the IDE's mcp.json configuration file.
    """
    OK = "OK"
    MISCONFIGURED = "MISCONFIGURED"
    NOT_FOUND = "NOT_FOUND"


# Default Nautex MCP configuration template
NAUTEX_CONFIG_TEMPLATE = {
    "nautex": {
        "command": "uvx",
        "args": ["nautex", "mcp"],
        # "cwd" will be dynamically added during configuration writing
    }
}


def validate_mcp_file(mcp_path: Path, cwd: Optional[Path] = None) -> MCPConfigStatus:
    """Validate a specific mcp.json file for correct nautex configuration.

    Args:
        mcp_path: Path to the mcp.json file
        cwd: Current working directory to validate against the cwd in the configuration.
             If None, the cwd field will not be validated.

    Returns:
        MCPConfigStatus indicating the validation result:
        - MCPConfigStatus.OK: Nautex entry exists and is correctly configured
        - MCPConfigStatus.MISCONFIGURED: File exists but nautex entry is incorrect
        - MCPConfigStatus.NOT_FOUND: No mcpServers section or nautex entry found
    """
    try:
        with open(mcp_path, 'r', encoding='utf-8') as f:
            mcp_config = json.load(f)

        # Check if mcpServers section exists
        if not isinstance(mcp_config, dict) or "mcpServers" not in mcp_config:
            logger.debug(f"No mcpServers section found in {mcp_path}")
            return MCPConfigStatus.NOT_FOUND

        mcp_servers = mcp_config["mcpServers"]
        if not isinstance(mcp_servers, dict):
            logger.debug(f"mcpServers is not a dict in {mcp_path}")
            return MCPConfigStatus.MISCONFIGURED

        # Check if nautex entry exists
        if "nautex" not in mcp_servers:
            logger.debug(f"No nautex entry found in mcpServers in {mcp_path}")
            return MCPConfigStatus.NOT_FOUND

        # Validate nautex entry against template
        nautex_config = mcp_servers["nautex"]
        
        # Basic validation of required fields
        if not is_nautex_config_valid(nautex_config):
            logger.debug(f"Invalid nautex configuration found in {mcp_path}")
            return MCPConfigStatus.MISCONFIGURED
            
        # Additional validation of cwd if provided
        if cwd is not None:
            config_cwd = nautex_config.get("cwd")
            if not config_cwd:
                logger.debug(f"Missing cwd in nautex configuration in {mcp_path}")
                return MCPConfigStatus.MISCONFIGURED
                
            # Resolve paths to absolute paths for comparison
            config_cwd_path = Path(config_cwd).resolve()
            cwd_resolved = cwd.resolve()
            
            if config_cwd_path != cwd_resolved:
                logger.debug(f"cwd mismatch in nautex configuration: {config_cwd_path} != {cwd_resolved}")
                return MCPConfigStatus.MISCONFIGURED
                
        logger.debug(f"Valid nautex configuration found in {mcp_path}")
        return MCPConfigStatus.OK

    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading/parsing mcp.json at {mcp_path}: {e}")
        return MCPConfigStatus.MISCONFIGURED


def is_nautex_config_valid(nautex_config: Any) -> bool:
    """Check if a nautex configuration entry matches our template.

    Args:
        nautex_config: The nautex configuration object from mcp.json

    Returns:
        True if configuration matches template, False otherwise
    """
    if not isinstance(nautex_config, dict):
        return False

    template_nautex_entry = NAUTEX_CONFIG_TEMPLATE.get("nautex")
    required_command = template_nautex_entry.get("command")
    required_args = template_nautex_entry.get("args")

    # Check for required fields
    has_required_fields = (
        nautex_config.get("command") == required_command and
        nautex_config.get("args") == required_args
    )
    
    # Check for cwd field - it must exist and be a string
    has_cwd = "cwd" in nautex_config and isinstance(nautex_config.get("cwd"), str)
    
    return has_required_fields and has_cwd


def write_mcp_configuration(target_path: Path, cwd: Optional[Path] = None) -> bool:
    """Write or update MCP configuration with Nautex CLI server entry.

    Reads the target MCP configuration file (or creates if not exists), adds/updates
    the 'nautex' server entry in mcpServers object, and saves the file.

    Args:
        target_path: Path where the MCP configuration will be written
        cwd: Current working directory to be added to the configuration. If None, 
             the current working directory will not be added.

    Returns:
        True if configuration was successfully written, False otherwise
    """
    try:
        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or create new one
        mcp_config = {}

        if target_path.exists():
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    mcp_config = json.load(f)
                logger.debug(f"Loaded existing mcp.json from {target_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error reading existing mcp.json, creating new: {e}")
                mcp_config = {}
        else:
            logger.debug(f"Creating new mcp.json at {target_path}")

        # Ensure mcp_config is a dict
        if not isinstance(mcp_config, dict):
            logger.warning("Invalid mcp.json format, recreating")
            mcp_config = {}

        # Ensure mcpServers section exists
        if "mcpServers" not in mcp_config:
            mcp_config["mcpServers"] = {}
        elif not isinstance(mcp_config["mcpServers"], dict):
            logger.warning("mcpServers is not a dict, recreating")
            mcp_config["mcpServers"] = {}

        # Add/update nautex entry
        nautex_config = NAUTEX_CONFIG_TEMPLATE.copy()
        
        # Add cwd to the nautex configuration if provided
        if cwd is not None:
            nautex_config["nautex"]["cwd"] = str(cwd.absolute())
            
        mcp_config["mcpServers"].update(nautex_config)

        # Write the configuration
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(mcp_config, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Nautex MCP configuration to {target_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to write MCP configuration: {e}")
        return False


# Test functions
def test_is_nautex_config_valid():
    """Test the is_nautex_config_valid function with various configurations."""
    print("Testing is_nautex_config_valid...")
    
    # Test with a valid configuration
    valid_config = {
        "command": "uvx",
        "args": ["nautex", "mcp"],
        "cwd": "/path/to/cwd"
    }
    assert is_nautex_config_valid(valid_config), "Valid configuration should be valid"
    
    # Test with a missing command
    invalid_config_1 = {
        "args": ["nautex", "mcp"],
        "cwd": "/path/to/cwd"
    }
    assert not is_nautex_config_valid(invalid_config_1), "Configuration with missing command should be invalid"
    
    # Test with incorrect args
    invalid_config_2 = {
        "command": "uvx",
        "args": ["wrong", "args"],
        "cwd": "/path/to/cwd"
    }
    assert not is_nautex_config_valid(invalid_config_2), "Configuration with incorrect args should be invalid"
    
    # Test with a missing cwd
    invalid_config_3 = {
        "command": "uvx",
        "args": ["nautex", "mcp"]
    }
    assert not is_nautex_config_valid(invalid_config_3), "Configuration with missing cwd should be invalid"
    
    # Test with a non-string cwd
    invalid_config_4 = {
        "command": "uvx",
        "args": ["nautex", "mcp"],
        "cwd": 123
    }
    assert not is_nautex_config_valid(invalid_config_4), "Configuration with non-string cwd should be invalid"
    
    # Test with a non-dict input
    assert not is_nautex_config_valid("not a dict"), "Non-dict input should be invalid"
    assert not is_nautex_config_valid(None), "None input should be invalid"
    
    print("is_nautex_config_valid tests passed!")
    return True


def test_write_mcp_configuration():
    """Test the write_mcp_configuration function."""
    print("Testing write_mcp_configuration...")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Test writing to a new file
        test_config_path = temp_path / "test_mcp.json"
        cwd = Path.cwd()
        
        # Write the configuration with cwd
        success = write_mcp_configuration(test_config_path, cwd)
        assert success, "write_mcp_configuration should return True on success"
        
        # Verify the file was created
        assert test_config_path.exists(), "Configuration file should exist"
        
        # Read the generated configuration
        with open(test_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Verify the configuration structure
        assert "mcpServers" in config, "Configuration should have mcpServers section"
        assert "nautex" in config["mcpServers"], "Configuration should have nautex entry"
        
        # Verify the nautex entry
        nautex_config = config["mcpServers"]["nautex"]
        assert nautex_config.get("command") == "uvx", "Command should be 'uvx'"
        assert nautex_config.get("args") == ["nautex", "mcp"], "Args should be ['nautex', 'mcp']"
        assert "cwd" in nautex_config, "Configuration should have cwd field"
        assert Path(nautex_config["cwd"]).is_absolute(), "cwd should be an absolute path"
        
        # Test updating an existing file with different content
        existing_config = {
            "mcpServers": {
                "existing": {
                    "command": "existing",
                    "args": ["existing"]
                }
            }
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f)
        
        # Update the configuration
        success = write_mcp_configuration(test_config_path, cwd)
        assert success, "write_mcp_configuration should return True when updating"
        
        # Read the updated configuration
        with open(test_config_path, 'r', encoding='utf-8') as f:
            updated_config = json.load(f)
        
        # Verify the updated configuration
        assert "mcpServers" in updated_config, "Updated configuration should have mcpServers section"
        assert "nautex" in updated_config["mcpServers"], "Updated configuration should have nautex entry"
        assert "existing" in updated_config["mcpServers"], "Updated configuration should preserve existing entries"
        
        # Test writing without cwd
        test_config_path_2 = temp_path / "test_mcp_no_cwd.json"
        success = write_mcp_configuration(test_config_path_2)
        assert success, "write_mcp_configuration should return True without cwd"
        
        # Read the generated configuration
        with open(test_config_path_2, 'r', encoding='utf-8') as f:
            config_no_cwd = json.load(f)
        
        # Verify the nautex entry has the required fields
        nautex_config_no_cwd = config_no_cwd["mcpServers"]["nautex"]
        assert nautex_config_no_cwd.get("command") == "uvx", "Command should be 'uvx'"
        assert nautex_config_no_cwd.get("args") == ["nautex", "mcp"], "Args should be ['nautex', 'mcp']"
    
    print("write_mcp_configuration tests passed!")
    return True


def test_validate_mcp_file():
    """Test the validate_mcp_file function."""
    print("Testing validate_mcp_file...")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_config_path = temp_path / "test_mcp.json"
        cwd = Path.cwd()
        
        # Test with a valid configuration
        valid_config = {
            "mcpServers": {
                "nautex": {
                    "command": "uvx",
                    "args": ["nautex", "mcp"],
                    "cwd": str(cwd.absolute())
                }
            }
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(valid_config, f)
        
        status = validate_mcp_file(test_config_path, cwd)
        assert status == MCPConfigStatus.OK, "Valid configuration should return OK"
        
        # Test with a missing mcpServers section
        invalid_config_1 = {}
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config_1, f)
        
        status = validate_mcp_file(test_config_path)
        assert status == MCPConfigStatus.NOT_FOUND, "Missing mcpServers should return NOT_FOUND"
        
        # Test with a missing nautex entry
        invalid_config_2 = {
            "mcpServers": {}
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config_2, f)
        
        status = validate_mcp_file(test_config_path)
        assert status == MCPConfigStatus.NOT_FOUND, "Missing nautex entry should return NOT_FOUND"
        
        # Test with an invalid nautex entry (missing command)
        invalid_config_3 = {
            "mcpServers": {
                "nautex": {
                    "args": ["nautex", "mcp"],
                    "cwd": str(cwd.absolute())
                }
            }
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config_3, f)
        
        status = validate_mcp_file(test_config_path)
        assert status == MCPConfigStatus.MISCONFIGURED, "Invalid nautex entry should return MISCONFIGURED"
        
        # Test with a mismatched cwd
        invalid_config_4 = {
            "mcpServers": {
                "nautex": {
                    "command": "uvx",
                    "args": ["nautex", "mcp"],
                    "cwd": "/different/path"
                }
            }
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config_4, f)
        
        status = validate_mcp_file(test_config_path, cwd)
        assert status == MCPConfigStatus.MISCONFIGURED, "Mismatched cwd should return MISCONFIGURED"
        
        # Test with a missing cwd when cwd is required
        invalid_config_5 = {
            "mcpServers": {
                "nautex": {
                    "command": "uvx",
                    "args": ["nautex", "mcp"]
                }
            }
        }
        with open(test_config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config_5, f)
        
        status = validate_mcp_file(test_config_path, cwd)
        assert status == MCPConfigStatus.MISCONFIGURED, "Missing cwd when required should return MISCONFIGURED"
        
        # Test with invalid JSON
        with open(test_config_path, 'w', encoding='utf-8') as f:
            f.write("invalid json")
        
        status = validate_mcp_file(test_config_path)
        assert status == MCPConfigStatus.MISCONFIGURED, "Invalid JSON should return MISCONFIGURED"
    
    print("validate_mcp_file tests passed!")
    return True


def run_tests():
    """Run all tests."""
    print("Running MCP utils tests...")
    
    test_results = [
        test_is_nautex_config_valid(),
        test_write_mcp_configuration(),
        test_validate_mcp_file()
    ]
    
    if all(test_results):
        print("All tests passed!")
        return True
    else:
        print("Some tests failed!")
        return False


if __name__ == "__main__":
    run_tests()