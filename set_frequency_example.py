import evalcontrol

evaluation_board = evalcontrol.AD9959()

# set the reference clock multiplier to x20
evaluation_board.set_clock_multiplier(20)

# set frequency on two channels to 20MHz
evaluation_board.set_frequency(20e6, channel=[0,1])

# set the relative phase of channel 0 to 90 degree
evaluation_board.set_phase(90, channel=0)
