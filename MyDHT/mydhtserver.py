import collections
import signal
from socket import *
import sys
import os
import thread
from HashRing import HashRing, Server
from MyDHTTable import MyDHTTable
from cmdapp import CmdApp
from mydhtclient import MyDHTClient

_block = 1024

class MyDHT(CmdApp):
    def __init__(self):
        """ Main class for the DHT server
        """
        CmdApp.__init__(self)
        self.remoteserver = None
        self.map = MyDHTTable()
        self.client = MyDHTClient()
        self.usage = \
        """
           -p, --port
             specify port (default: 50140)
           -h, --hostname
             specify hostname (default: localhost)
        """

    def cmdlinestart(self):
        """ Start server from cmdline
        get -p, --port and -h, --hostname parameters
        """
        try:
            port = int(self.getarg("-p") or self.getarg("--port",50140))
            host = self.getarg("-h") or self.getarg("--hostname","localhost")
            # Check if we should connect to existing ring
            remoteserver = self.getarg("-s") or self.getarg("-server")
            # Start the server
            self.start(host,port,remoteserver)
        except ValueError:
            self.help()

    def start(self,host,port,remoteserver,verbose=None,logfile=None,is_process=False):
        self.thisserver = Server(host,port)
        self.remoteserver = remoteserver
        self.is_process = thread
        if verbose:
            self.verbose = True
        if logfile:
            sys.stdout = open(logfile,"w")
        self.serve()

    def addnewserver(self,newserverhostport):
        """ Adds a new server to all existing nodes and
            sends the current ring back to it.
        """
        self.debug("adding:",newserverhostport)
        host, port = newserverhostport.split(":")
        newserver = Server(host,port)

        # Add the new server to all existing nodes
        for server in self.hashring.ring.values():
            if self.thisserver != server:
                self.client.sendcommand(server,"addnode",newserver)
        # Convert to a string list
        ring = map(lambda serv: str(serv),set(self.hashring.ring.values()))
        # Add new server to this ring
        self.hashring.add_node(newserver)
        # Return |-separated list of nodes
        return "|".join(ring)

    def serverthread(self,clientsock):
        """ Thread that handles a client
            `clientsock` is the socket where the client is connected
            perform the operation and connect to another server if necessary
        """
        sockfile = clientsock.makefile('r') # wrap socket in dup file obj
        command = sockfile.readline()[:-1]

        # Commands that always should end up on this server
        if command == "join":
            server = sockfile.readline()[:-1]
            status = self.addnewserver(server)
        elif command == "addnode":
            newserver = sockfile.readline()[:-1]
            self.hashring.add_node(newserver)
            status = "added by "+str(self.thisserver)
        elif command in ["PUT","GET","DEL"]:
            key = sockfile.readline()[:-1]
            key_is_at = self.hashring.get_node(key)
            self.debug(key,"is at",str(key_is_at),"according to",str(self.hashring))
            value = None
            if command == MyDHTTable.PUT:
                value = sockfile.readline()[:-1]

            # Check if key is found locally
            if self.thisserver == key_is_at:
                status = self.map.perform(command,key,value)
            else:
                # Forward the request to the correct server
                status = self.client.sendcommand(key_is_at,command,key,value)
        else:
            self.debug("Invalid command",command)
            status = "INVALID_COMMAND"

        # Send status or "BAD_STATUS"
        clientsock.send(status or "BAD_STATUS")
        clientsock.close()

    def signal_handler(self,signal,frame):
        """ Handle SIGINT
        """
        self.debug("Exiting from SIGINT")
        if self.is_process:
            # Exit softly if this is a subprocess
            os._exit(0)
        else:
            # Exit hard if standalone
            sys.exit(0)

    def serve(self):
        """ Main server process
            Starts a new thread for new clients
        """
        if not self.thisserver:
            self.usage()

        # Register SIGINT handler
        signal.signal(signal.SIGINT, self.signal_handler)

        if self.remoteserver:
            remotehost, remoteport = self.remoteserver.split(":")
            remoteserver = Server(remotehost,remoteport)
            # Send a join command to the existing server
            ring = self.client.sendcommand(remoteserver,"join",self.thisserver)
            self.debug("got ring from server:",str(ring))
            # Convert |-separated list to Server-instances
            nodes =  map(lambda serv: Server(serv.split(":")[0],serv.split(":")[1]) ,ring.split("|"))
            # Initialize local hashring
            self.hashring = HashRing(nodes)
            self.hashring.add_node(self.thisserver)
        else:
            # First server so this server is added
            self.hashring = HashRing([self.thisserver])

        self.debug("Starting server at",str(self.thisserver))
        serversock = socket(AF_INET,SOCK_STREAM)
        try:
            serversock.bind((self.thisserver.bindaddress()))
            serversock.listen(5)
            while(1):
                clientsock, clientaddr = serversock.accept()
                #self.debug("Server connected by", clientaddr)
                thread.start_new_thread(self.serverthread, (clientsock,))
        except error, msg:
            print "Unable to bind to socket: ",msg

if __name__ == "__main__":
    MyDHT().cmdlinestart()