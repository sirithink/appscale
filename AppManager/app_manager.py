# Programmer: Navraj Chohan
import logging
import os
import random
import SOAPpy
import sys
import time
import urllib

from M2Crypto import SSL

import god_app_interface

sys.path.append(os.path.join(os.path.dirname(__file__), "../lib/"))
import appscale_info
import constants
import god_interface 

# IP used for binding app_manager SOAP service
DEFAULT_IP = '127.0.0.1'

# Most attempts to see if an application server comes up before failing
MAX_FETCH_ATTEMPTS = 7

# The PID number to return when a process did not start correctly
BAD_PID = -1

# Required configuration fields for starting an application
REQUIRED_CONFIG_FIELDS = ['app_name', 
                          'app_port', 
                          'language', 
                          'load_balancer_ip', 
                          'load_balancer_port', 
                          'xmpp_ip',
                          'dblocations']

def start_app(config):
  """ Starts a Google App Engine application on this host machine. It 
      will start it up and then proceed to fetch the main page.
  
  Args:
    config: a dictionary that contains 
       app_name: Name of the application to start
       app_port: Port to start on 
       language: What language the app is written in
       load_balancer_ip: Public ip of load balancer
       load_balancer_port: Port of load balancer
       xmpp_ip: IP of XMPP service 
       dblocations: List of database locations 
  Returns:
    PID of process on success, -1 otherwise
  Raises:
    TypeError if config is not a dictionary
  """

  if not isinstance(config, dict): raise TypeError

  if not is_config_valid(config): 
    logging.error("Invalid configuration for application")
    return BAD_PID

  logging.info("Starting %s application %s"%(config['language'], 
                                             config['app_name']))

  start_cmd = ""
  stop_cmd = ""
  env_vars = {}
  watch = "app___" + config['app_name'] +\
          "-" + str(config['app_port'])

 
  if config['language'] == constants.PYTHON:
    start_cmd = create_python_start_cmd(config['app_name'],
                            config['load_balancer_ip'],
                            config['app_port'],
                            config['load_balancer_ip'],
                            config['load_balancer_port'],
                            config['xmpp_ip'],
                            config['dblocations'])
    stop_cmd = create_python_stop_cmd(config['app_port'])
  elif config['language'] == constants.JAVA:
    start_cmd = create_java_start_cmd(config['app_name'],
                            config['load_balancer_ip'],
                            config['app_port'],
                            config['load_balancer_ip'],
                            config['load_balancer_port'],
                            config['xmpp_ip'],
                            config['dblocations'])
    stop_cmd = create_java_stop_cmd(config['app_port'])
  else:
    logging.error("Unknown application language %s for appname %s"\
                  %(config['language'], config['app_name'])) 
    return BAD_PID

  config_file_loc = god_app_interface.create_config_file(watch,
                                                     start_cmd, 
                                                     stop_cmd, 
                                                     [config['app_port']],
                                                     env_vars)

  if not god_interface.start(config_file_loc, watch):
    logging.error("Unable to start application server with god")
    return BAD_PID

  if not wait_on_app(int(config['app_port'])):
    logging.error("Application server did not come up in time, \
                   removing god watch")
    god_interface.stop(watch)
    return BAD_PID

  return get_pid_from_port(config['app_port'])

def stop_app(app_name):
  """ Stops a Google App Engine application on this host machine.

  Args:
    app_name: Name of application to stop
  Returns:
    True on success, False otherwise
  """

  logging.info("Stopping application %s"%app_name)
  return True

def get_app_listing():
  """ Returns a dictionary on information applications
      running on this host.

  Returns:
    A dictionary of information on apps running on this host.
  """

  return {}

######################
# Private Functions
######################
def get_pid_from_port(port):
  """ Gets the PID of the process binded to the given port
   
  Args:
    port: The port in which you want the process binding it
  Returns:
    The PID on success, and -1 on failure
  """ 
  s = os.popen("lsof -i:" + str(port) + " | grep -v COMMAND | awk {'print $2'}")
  pid = s.read().rstrip()
  if pid:
    return int(pid)
  else: 
    return BAD_PID
 
def wait_on_app(port):
  """ Attempts fetch from the given port and backs off until it 
     comes up, or times out.
  
  Args:
    port: The port to fetch from
  Returns:
    True on success, False otherwise
  """

  backoff = 1
  retries = MAX_FETCH_ATTEMPTS
  private_ip = appscale_info.get_private_ip()

  while retries > 0:
    try:
      f = urllib.urlopen("http://" + private_ip + ":" + str(port))
      return True
    except IOError:
      retries -= 1

    logging.warning("Application was not up, retrying in %d seconds"%backoff)
    time.sleep(backoff)
    backoff *= 2

  logging.error("Application did not come up on port %d after %d attemps"%\
                (port, MAX_FETCH_ATTEMPTS))
  return False
     
def choose_db_location(db_locations):
  """ Given a string containing multiple datastore locations
  select one randomly.

  Args:
    db_locations: A list of datastore locations
  Returns:
    One IP location randomly selected from the string.
  Raise:
    ValueError if there are no locations given in the args.
  """
  if len(db_locations) == 0: raise ValueError("DB locations \
     were not correctly set")
  index = random.randint(0, len(db_locations) - 1)
  return db_locations[index]

def create_python_app_env(public_ip, port, app_name):
  """ Returns the environment variables used to start a python 
  application
  
  Args:
    public_ip: The public IP
    port: The port the application is using
    app_name: The name of the application to be run
  Returns:
    A dictionary containing the environment variables
  """

  env_vars = {}
  env_vars['MY_IP_ADDRESS'] = public_ip
  env_vars['MY_PORT'] = str(port)
  env_vars['APPNAME'] = app_name
  env_vars['GOMAXPROCS'] = appscale_info.get_num_cpus()

  return env_vars

def create_java_app_env():
  """ Returns the environment variables used to start a java 
  application
  
  Args: None
  Returns:
    A dictionary containing the environment variables  
  """

  return {}

def create_python_start_cmd(app_name,
                            login_ip, 
                            port, 
                            load_balancer_host, 
                            load_balancer_port,
                            xmpp_ip,
                            db_locations):
  """
  Creates the command line to run the python application server.
  
  Args:
    app_name: The name of the application to run
    login_ip: The public IP
    port: The local port the application server will bind to
    load_balancer_host: The host of the load balancer
    load_balancer_port: The port of the load balancer
    xmpp_ip: The IP of the XMPP service
  Returns:
    A string of the start command.
  """

  db_location = choose_db_location(db_locations)

  cmd = ["python2.5 ",
         constants.APPSCALE_HOME + "/AppServer/dev_appserver.py",
         "-p " + str(port),
         "--cookie_secret " + appscale_info.get_secret(),
         "--login_server " + login_ip,
         "--admin_console_server ''",
         "--nginx_port " + str(load_balancer_port),
         "--nginx_host " + str(load_balancer_host),
         "--require_indexes",
         "--enable_sendmail",
         "--xmpp_path " + xmpp_ip,
         "--uaserver_path " + db_location + ":"\
               + str(constants.UA_SERVER_PORT),
         "--datastore_path " + db_location + ":"\
               + str(constants.DB_SERVER_PORT),
         "--history_path /var/apps/" + app_name\
               + "/data/app.datastore.history",
         "/var/apps/" + app_name + "/app",
         "-a " + appscale_info.get_private_ip()]
  
  return ' '.join(cmd)

def create_java_start_cmd():
  """
  """

  return

def create_python_stop_cmd(port):
  """ This creates the stop command for an application which is 
  uniquely identified by a port number. Additional portions of the 
  start command are included to prevent the termination of other 
  processes. 
  
  Args: 
    port: The port which the application server is running
  Returns:
    A string of the stop command.
  """

  cmd = ["python2.5",
         constants.APPSCALE_HOME + "/AppServer/dev_appserver.py",
         "-p " + str(port),
         "--cookie_secret " + appscale_info.get_secret()]
  cmd = ' '.join(cmd)

  stop_cmd = "ps aux | grep '" + cmd +\
             "' | grep -v grep | awk '{ print $2 }' | xargs -d '\n' kill -9"
  return stop_cmd

def create_java_stop_cmd():
  """ This creates the stop command for an application which is 
  uniquely identified by a port number. Additional portions of the 
  start command are included to prevent the termination of other 
  processes. 
  
  Args: 
    port: The port which the application server is running
  Returns:
    A string of the stop command.
  """

  return ""

def run_python_app():
  """
  """
  # validate that the app.yaml configuration file is there

  return 

def run_java_app():
  """
  """
  # validate that the xml configuration file is there
  return

def is_config_valid(config):
  """ Takes a configuration and checks to make sure all required properties 
    are present
 
  Args:
    config: The dictionary to validate
  Returns:
    True if valid, false otherwise
  """
  for ii in REQUIRED_CONFIG_FIELDS:
    if not ii in config:
      return False 
  return True

def usage():
  """ Prints usage of this program """
  print "args: --help or -h for this menu"

################################
# MAIN
################################
if __name__ == "__main__":
  for ii in range(1, len(sys.argv)):
    if sys.argv[ii] in ("-h", "--help"):
      usage()
      sys.exit()
  
  server = SOAPpy.SOAPServer((DEFAULT_IP, constants.APP_MANAGER_PORT))
 
  server.registerFunction(start_app)
  server.registerFunction(stop_app)

  while 1:
    try: 
      server.serve_forever()
    except SSL.SSLError: 
      pass
 
