# evalcontrol

A python library to control the AD9959 DDS Evaluation Board. This library is based on the 
[MIT Labview drivers](http://cua.mit.edu/AD9959-USB-drivers/) and the [official documentation of the AD9959](http://www.analog.com/media/en/technical-documentation/data-sheets/AD9959.pdf).

## Installation
To install the package from source simply do
```
git clone https://github.com/Schlabonski/evalcontrol`
cd evalcontrol
python3 setup.py install
```
Keep in mind that this library works on top of `pyusb` which uses `libusb` so these packages should both be installed as well.
To install `liusb` on windows, see instructions below.

## Use without sudo
If you want to use the library, i.e. access the evaluation board, without root rights run the following steps first.
 1. Add the user to the plugdev group
 `sudo useradd -G plugdev USERNAME`
 2. Add the evaluation board to the plugdev group by edditing a new rules file
 `sudo vim /etc/udev/rules.d/10-ad9959.rules`
  and adding the following line
  `ATTRS{idProduct}=="PRODUCT_ID", ATTRS{idVendor}=="VENDOR_ID", MODE="666", GROUP="plugdev"`
  where PRODUCT_ID and VENDOR_ID are replaced by the respective IDs (mind the quotes).
 3. Reload the udev rules
 `sudo udevadm trigger`
  
## Use with artiq
 To use the package within `artiq` just activate the corresponding virtual environment and run 
 `python3 setup.py install`
 When accessing the device in the preparation phase of an experiment, use the `AD9959.reset()` method to prevent USBErrors due to timeout.

## Use on Windows
To use this package on windows, you need to install a port of the libusb driver.
 1. Download from https://sourceforge.net/projects/libusb-win32/
 2. copy `libusb0.dll` to C:\Windows\System32
 3. copy `libusb0.sys` to C:\Windows\System32\drivers
 4. add a filter for the AD9959 using the `install-filter-win` utility
