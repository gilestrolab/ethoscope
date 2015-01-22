

def get_machine_id():
    """
    Reads the machine ID file and returns the value.
    """
    f = open('/etc/machineId', 'r')
    pi_id = f.readline()
    f.close()
    return pi_id