#!/usr/bin/env python3
"""
Dev Lab Setup Script

This script sets up a Python virtual environment and installs dependencies
for the dev-lab platform-agnostic Kubernetes development environment.

Only requirement: Docker must be installed and running.
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def run_command(cmd, check=True, capture_output=False):
    """Run a command with error handling"""
    try:
        result = subprocess.run(cmd, shell=True, check=check, 
                              capture_output=capture_output, text=True)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}")
        print(f"Exit code: {e.returncode}")
        if capture_output and e.stdout:
            print(f"Stdout: {e.stdout}")
        if capture_output and e.stderr:
            print(f"Stderr: {e.stderr}")
        raise

def check_python():
    """Check Python version"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        return False
    
    print(f"✅ Python {sys.version.split()[0]} detected")
    return True

def check_docker():
    """Check if Docker is available"""
    try:
        result = run_command("docker --version", capture_output=True)
        print(f"✅ {result.stdout.strip()}")
        
        # Check if Docker daemon is running
        result = run_command("docker info", capture_output=True, check=False)
        if result.returncode != 0:
            print("❌ Docker daemon is not running. Please start Docker.")
            return False
        
        print("✅ Docker daemon is running")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker is not installed or not in PATH")
        print("Please install Docker from: https://docs.docker.com/get-docker/")
        return False

def setup_venv():
    """Set up Python virtual environment"""
    script_dir = Path(__file__).parent
    venv_dir = script_dir / "venv"
    
    if venv_dir.exists():
        print("🔄 Virtual environment already exists")
    else:
        print("🐍 Creating Python virtual environment...")
        run_command(f"{sys.executable} -m venv {venv_dir}")
        print("✅ Virtual environment created")
    
    # Determine activation script based on platform
    if platform.system() == "Windows":
        activate_script = venv_dir / "Scripts" / "activate.bat"
        pip_executable = venv_dir / "Scripts" / "pip.exe"
        python_executable = venv_dir / "Scripts" / "python.exe"
    else:
        activate_script = venv_dir / "bin" / "activate"
        pip_executable = venv_dir / "bin" / "pip"
        python_executable = venv_dir / "bin" / "python"
    
    # Install requirements
    requirements_file = script_dir / "requirements.txt"
    if requirements_file.exists():
        print("📦 Installing Python dependencies...")
        run_command(f"{pip_executable} install --upgrade pip")
        run_command(f"{pip_executable} install -r {requirements_file}")
        print("✅ Dependencies installed")
    else:
        print(f"❌ Requirements file not found: {requirements_file}")
        return False
    
    return {
        "venv_dir": venv_dir,
        "activate_script": activate_script,
        "python_executable": python_executable,
        "pip_executable": pip_executable
    }

def create_wrapper_scripts(venv_info):
    """Create platform-specific wrapper scripts"""
    script_dir = Path(__file__).parent
    venv_python = venv_info["python_executable"]
    
    # Create cross-platform wrapper
    wrapper_content = f'''#!/usr/bin/env python3
"""
Dev Lab Wrapper Script
Automatically uses the virtual environment
"""
import sys
import subprocess
from pathlib import Path

# Use the virtual environment Python
venv_python = Path(__file__).parent / "venv" / {"Scripts" if sys.platform == "win32" else "bin"} / "python"
devlab_script = Path(__file__).parent / "devlab.py"

# Pass all arguments to the actual script
cmd = [str(venv_python), str(devlab_script)] + sys.argv[1:]
subprocess.run(cmd)
'''
    
    wrapper_file = script_dir / "devlab"
    with open(wrapper_file, 'w') as f:
        f.write(wrapper_content)
    
    # Make executable on Unix-like systems
    if platform.system() != "Windows":
        os.chmod(wrapper_file, 0o755)
    
    # Create Windows batch file
    if platform.system() == "Windows":
        batch_content = f'''@echo off
"{venv_python}" "{script_dir / "devlab.py"}" %*
'''
        batch_file = script_dir / "devlab.bat"
        with open(batch_file, 'w') as f:
            f.write(batch_content)
    
    return wrapper_file

def show_usage_instructions(wrapper_file):
    """Show usage instructions"""
    script_dir = Path(__file__).parent
    
    print("\n" + "="*60)
    print("🎉 Dev Lab Setup Complete!")
    print("="*60)
    print("\nThe dev-lab environment is now ready to use.")
    print("All Kubernetes tools run in containers - no local installation needed!")
    print("\n📖 Quick Start:")
    print(f"   cd {script_dir}")
    
    if platform.system() == "Windows":
        print("   .\\devlab.bat bootstrap      # Create cluster and setup services")
        print("   .\\devlab.bat deploy         # Deploy applications")
        print("   .\\devlab.bat status         # Check status")
        print("   .\\devlab.bat kubectl -- get pods -A")
        print("   .\\devlab.bat cleanup        # Clean up everything")
    else:
        print("   ./devlab bootstrap          # Create cluster and setup services")
        print("   ./devlab deploy             # Deploy applications")
        print("   ./devlab status             # Check status")
        print("   ./devlab kubectl -- get pods -A")
        print("   ./devlab cleanup            # Clean up everything")
    
    print("\n🐳 Container-based tools available:")
    print("   • kubectl (Kubernetes CLI)")
    print("   • helm (Package manager)")
    print("   • linkerd (Service mesh CLI)")
    print("   • kind (Kubernetes in Docker)")
    print("   • flux (GitOps toolkit)")
    
    print("\n🌟 Benefits:")
    print("   ✅ Platform-agnostic (Windows, macOS, Linux)")
    print("   ✅ Only requires Docker")
    print("   ✅ No local tool installation")
    print("   ✅ Clean, reproducible environment")
    print("   ✅ Easy cleanup and reset")
    
    print("\n📁 Project structure:")
    print(f"   {script_dir.parent}/")
    print("   ├── python/              # Python-based dev-lab tools")
    print("   ├── config/              # External configuration files")
    print("   ├── cluster/             # Cluster configuration")
    print("   └── scripts/             # Original bash scripts (deprecated)")

def main():
    """Main setup function"""
    print("🚀 Dev Lab Platform-Agnostic Setup")
    print("=" * 40)
    
    # Check prerequisites
    if not check_python():
        sys.exit(1)
    
    if not check_docker():
        sys.exit(1)
    
    # Setup virtual environment
    try:
        venv_info = setup_venv()
        if not venv_info:
            sys.exit(1)
        
        # Create wrapper scripts
        wrapper_file = create_wrapper_scripts(venv_info)
        
        # Show usage instructions
        show_usage_instructions(wrapper_file)
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()