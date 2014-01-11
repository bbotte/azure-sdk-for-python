#-------------------------------------------------------------------------
# Copyright (c) Microsoft.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#--------------------------------------------------------------------------
import base64
import sys

if sys.version_info < (3,):
    from httplib import HTTPSConnection, HTTPConnection, HTTP_PORT, HTTPS_PORT
else:
    from http.client import HTTPSConnection, HTTPConnection, HTTP_PORT, HTTPS_PORT

from azure.http import HTTPError, HTTPResponse
from azure import _USER_AGENT_STRING

class _HTTPClient:
    ''' 
    Takes the request and sends it to cloud service and returns the response.
    '''

    def __init__(self, service_instance, cert_file=None, account_name=None, account_key=None, service_namespace=None, issuer=None, protocol='https'):
        '''
        service_instance: service client instance. 
        cert_file: certificate file name/location. This is only used in hosted service management.
        account_name: the storage account.
        account_key: the storage account access key for storage services or servicebus access key for service bus service.
        service_namespace: the service namespace for service bus.
        issuer: the issuer for service bus service.
        '''
        self.service_instance = service_instance
        self.status = None
        self.respheader = None
        self.message = None
        self.cert_file = cert_file
        self.account_name = account_name
        self.account_key = account_key    
        self.service_namespace = service_namespace    
        self.issuer = issuer
        self.protocol = protocol
        self.proxy_host = None
        self.proxy_port = None
        self.proxy_user = None
        self.proxy_password = None

        # If on Windows then use winhttp HTTPConnection instead of httplib HTTPConnection due to the 
        # bugs in httplib HTTPSConnection. We've reported the issue to the Python 
        # dev team and it's already fixed for 2.7.4 but we'll need to keep this workaround meanwhile.
        self.use_httplib = not sys.platform.lower().startswith('win')

    def set_proxy(self, host, port, user, password):
        '''
        Sets the proxy server host and port for the HTTP CONNECT Tunnelling.

        host: Address of the proxy. Ex: '192.168.0.100'
        port: Port of the proxy. Ex: 6000
        user: User for proxy authorization.
        password: Password for proxy authorization.
        '''
        self.proxy_host = host
        self.proxy_port = port
        self.proxy_user = user
        self.proxy_password = password

    def get_connection(self, request):
        ''' Create connection for the request. '''
        protocol = request.protocol_override if request.protocol_override else self.protocol
        target_host = request.host
        target_port = HTTP_PORT if protocol == 'http' else HTTPS_PORT

        if not self.use_httplib:
            import azure.http.winhttp
            connection = azure.http.winhttp._HTTPConnection(target_host, cert_file=self.cert_file, protocol=protocol)
            proxy_host = self.proxy_host
            proxy_port = self.proxy_port
        else:
            if self.proxy_host:
                proxy_host = target_host
                proxy_port = target_port
                host = self.proxy_host
                port = self.proxy_port
            else:
                host = target_host
                port = target_port

            if protocol == 'http':
                connection = HTTPConnection(host, int(port))
            else:
                connection = HTTPSConnection(host, int(port), cert_file=self.cert_file)

        if self.proxy_host:
            headers = None
            if self.proxy_user and self.proxy_password:
                auth = base64.encodestring("{0}:{1}".format(self.proxy_user, self.proxy_password))
                headers = {'Proxy-Authorization': 'Basic {0}'.format(auth)}
            connection.set_tunnel(proxy_host, int(proxy_port), headers)

        return connection

    def send_request_headers(self, connection, request_headers):
        if self.use_httplib:
            if self.proxy_host:
                for i in connection._buffer:
                    if i.startswith("Host: "):
                        connection._buffer.remove(i)
                connection.putheader('Host', "{0}:{1}".format(connection._tunnel_host, connection._tunnel_port))

        for name, value in request_headers:
            if value:
                connection.putheader(name, value)

        connection.putheader('User-Agent', _USER_AGENT_STRING)
        connection.endheaders()

    def send_request_body(self, connection, request_body):
        if request_body:
            assert isinstance(request_body, bytes)
            connection.send(request_body)
        elif (not isinstance(connection, HTTPSConnection) and 
              not isinstance(connection, HTTPConnection)):
            connection.send(None)
     
    def perform_request(self, request):
        ''' Sends request to cloud service server and return the response. '''
        connection = self.get_connection(request)
        try:
            connection.putrequest(request.method, request.path)

            if not self.use_httplib:
                if self.proxy_host and self.proxy_user:
                    connection.set_proxy_credentials(self.proxy_user, self.proxy_password)

            self.send_request_headers(connection, request.headers)
            self.send_request_body(connection, request.body)

            resp = connection.getresponse()
            self.status = int(resp.status)
            self.message = resp.reason
            self.respheader = headers = resp.getheaders()

            # for consistency across platforms, make header names lowercase
            for i, value in enumerate(headers):
                headers[i] = (value[0].lower(), value[1])

            respbody = None
            if resp.length is None:
                respbody = resp.read()
            elif resp.length > 0:
                respbody = resp.read(resp.length)

            response = HTTPResponse(int(resp.status), resp.reason, headers, respbody)
            if self.status >= 300:
                raise HTTPError(self.status, self.message, self.respheader, respbody)
        
            return response
        finally:
            connection.close()