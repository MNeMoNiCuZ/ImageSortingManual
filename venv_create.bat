:: Guides the user through a virtual environment creation process
:: Version 1.4
@echo off
setlocal enabledelayedexpansion

echo ------------------------------------------------------------------------------
echo VENV Installation Script - Helps you create a virtual environment (2025-12-30)
echo ------------------------------------------------------------------------------

:: Temporarily disable delayed expansion to check for "!" in the path
setlocal disabledelayedexpansion
echo You are about to create a virtual environment in: %CD%
set "CURRENT_PATH=%CD%"
set "MODIFIED_PATH=%CURRENT_PATH:!=%"
if not "%CURRENT_PATH%"=="%MODIFIED_PATH%" (
    echo WARNING: The current directory contains a "!" character, which may cause issues. Running 'pip install -r requirements' may have trouble installing. Proceed at your own risk.
)
endlocal
setlocal enabledelayedexpansion


:: Initialize counter
set COUNT=0

:: Directly parse the output of py -0p to get versions and their paths
for /f "tokens=1,*" %%a in ('py -0p') do (
    :: Filter lines that start with a dash, indicating a Python version, and capture the path
    echo %%a | findstr /R "^[ ]*-" > nul && (
        set /a COUNT+=1
        set "pythonVersion=%%a"
        :: a quick, dirty but understandable solution
        set "pythonVersion=!pythonVersion:-32=!"
        set "pythonVersion=!pythonVersion:-64=!"
        set "pythonVersion=!pythonVersion:-=!"
        set "pythonVersion=!pythonVersion:V:=!"
        set "PYTHON_VER_!COUNT!=!pythonVersion!"
        set "PYTHON_PATH_!COUNT!=%%b"  :: Store the path in a separate variable
    )
)

:: Make sure at least one Python version was found
if %COUNT%==0 (
    echo No Python installations found via Python Launcher. Exiting.
    goto end
)

echo.
echo --------------
echo Python Version
echo --------------
echo Please choose which of your installed python versions to use:
for /L %%i in (1,1,%COUNT%) do (
    echo %%i. -V:!PYTHON_VER_%%i! at !PYTHON_PATH_%%i!
)
echo.

:: Prompt user to select a Python version (default is 1)
set /p PYTHON_SELECTION="Select a Python version by number (Press Enter for default = '1'): "
if "!PYTHON_SELECTION!"=="" set PYTHON_SELECTION=1

:: Extract the selected Python version tag and parse the version number more accurately
set SELECTED_PYTHON_VER=!PYTHON_VER_%PYTHON_SELECTION%!

echo Using Python version %SELECTED_PYTHON_VER%
echo.

:: Prompt for virtual environment name with default 'venv'
echo ------------------------
echo Virtual Environment Name
echo ------------------------
echo Select the name of your virtual environment. Using the default 'venv' is fine.
set VENV_NAME=venv
set /p VENV_NAME="Enter the name for your virtual environment (Press Enter for default 'venv'): "
if "!VENV_NAME!"=="" set VENV_NAME=venv

:: Create the virtual environment using the selected Python version
echo.
echo Creating virtual environment named %VENV_NAME%...

py -%SELECTED_PYTHON_VER% -m venv %VENV_NAME%

:: Add .gitignore to the virtual environment folder
echo Creating .gitignore in the %VENV_NAME% folder...
(
echo # Ignore all content in the virtual environment directory
echo *
echo # Except this file
echo !.gitignore
) > %VENV_NAME%\.gitignore

:: Generate the venv_activate.bat file
echo Generating venv_activate.bat...
(
echo @echo off
echo cd %%~dp0
echo set VENV_PATH=%VENV_NAME%
echo.
echo echo Activating virtual environment...
echo call "%%VENV_PATH%%\Scripts\activate"
echo echo Virtual environment activated.
echo cmd /k
) > venv_activate.bat

:: Activate the virtual environment and upgrade pip
echo.
echo ---------------------
echo Upgrading pip install
echo ---------------------
echo Activating virtual environment and upgrading pip...
call "%VENV_NAME%\Scripts\activate"
"%VENV_NAME%\Scripts\python.exe" -m pip install --upgrade pip

:: uv pip package installer
echo.
echo ------------------------
echo uv pip package installer
echo ------------------------
echo Installing 'uv' package...
pip install uv

:: Check if requirements.txt exists and handle installation
echo.
echo ---------------------------------------------
echo Installing dependencies from requirements.txt
echo ---------------------------------------------
:: Prompt the user for installation of requirements.txt
if exist requirements.txt (
    echo requirements.txt found.
    
    set /p INSTALL_REQUIREMENTS="Do you wish to run 'uv pip install -r requirements.txt'? (Y/N) (Press Enter for default 'Y'): "
    
    if not defined INSTALL_REQUIREMENTS set INSTALL_REQUIREMENTS=Y
    if /I "!INSTALL_REQUIREMENTS!"=="Y" (
        uv pip install -r requirements.txt
    ) else (
        echo Skipping requirements installation.
    )
) else (
    echo requirements.txt not found. Skipping requirements installation.
)

:: List installed packages
echo.
echo Listing installed packages...
pip list

echo.
echo Setup complete. Your virtual environment is ready.
echo To deactivate the virtual environment, type 'deactivate'.

:: Keep the command prompt open
cmd /k

:cleanup
:: Clean up
echo Cleanup complete.
endlocal