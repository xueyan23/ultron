# -*- coding: UTF-8 -*-
#!/usr/bin/python  
import time
import datetime
import subprocess, re  
from subprocess import Popen  
from subprocess import PIPE
import time
import datetime


a = 0
    
keyword = "autron_fan.py"  # 設置 grep 的關鍵字  
ptn = re.compile("\s+")  

p1 = Popen(["ps", "-aux"], stdout=PIPE)  
p2 = Popen(["grep", keyword], stdin=p1.stdout, stdout=PIPE)  
p1.stdout.close()  
output = p2.communicate()[0]  
print("Output:\n{0}".format(output))


lines = output.strip().split("\n")  
for line in lines:  
    items = ptn.split(line)
    if items[10] != "python3.9":
        #print("kill {0}...".format(items[1], subprocess.call(["kill", items[1]])))
	print(items[10])
    else:
        a = a+1
    #print("kill {0}...".format(items[1], subprocess.call(["kill", items[1]]))) 
#subprocess.Popen(['python3.9','/var/www/html/ultron/autron_fan/autron_fan.py'])

print(a)

if a == 0:
    subprocess.Popen(['python3.9','/var/www/html/ultron/autron_fan/autron_fan.py'])
