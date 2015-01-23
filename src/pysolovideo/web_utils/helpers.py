

def get_machine_id():
    """
    Reads the machine ID file and returns the value.
    """
    f = open('/etc/machine-id', 'r')
    pi_id = f.readline()
    pi_id = pi_id.strip()
    f.close()
    return pi_id