# evalcontrol

A python library to control the AD9959 DDS Evaluation Board

## Usage without sudo
If you want to use the library, i.e. access the evaluation board, without root rights run the following steps first.
 1. Add the user to the plugdev group
 `sudo useradd -G plugdev USERNAME`
 2. Add the evaluation board to the plugdev group by edditing a new rules file
 `sudo vim /etv/udev/rules.d/10-ad9959.rules`
  and adding the following line
  `ATTRS{idProduct}=="PRODUCT_ID", ATTRS{idVendor}=="VENDOR_ID", MODE="666", GROUP="plugdev"`
  where PRODUCT_ID and VENDOR_ID are replaced by the respective IDs (mind the quotes).
 3. Reload the udev rules
 `sudo udevadm trigger`
  
## Usage with artiq
 To use the package within `artiq` just activate the corresponding virtual environment and run 
 `python3 setup.py install`
 When accessing the device in the preparation phase of an experiment, use the `AD9959.reset()` method to prevent USBErrors due to timeout.
