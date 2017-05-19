from multiprocessing import Process, Queue
import time
import logging
import re
from neo4j.v1 import GraphDatabase, basic_auth

logging.basicConfig(level=logging.WARNING, format='(%(threadName)s: %(asctime)s) %(message)s',)

TEXT_QUEUE_SIZE = 10000
DB_QUEUE_SIZE = 21000000

text_queue = Queue(TEXT_QUEUE_SIZE)
# db_queue = queue.Queue(DB_QUEUE_SIZE)

class FileReader(Process):
    def run(self):
        inPage = False
        with open('enwiki-20170420-pages-articles.xml', 'r') as wiki:
            pc = 0
            ft = 0
            ID = 0
            count = 0
            inText = False
            isRedirect = None
            for line in wiki:
                line = line.strip()
                if line == '</page>':
                    inPage = False
                elif inPage:
                    if pc == 1:
                        pc += 1
                    elif pc == 2:
                        #Figure out namespace
                        ft = int(line[4:-5])
                        pc += 1
                    elif pc == 3:
                        ID = int(line[4:-5])
                        pc += 1
                    elif pc == 4:
                        if line[0:9] == "<redirect":
                            isRedirect = True
                        pc += 1
                    elif pc > 4:
                        if line[0:5] == '<text':
                            inText = True
                        if not isRedirect and (ft == 0 or ft == 6) and inText:
                            text_queue.put((ft, ID, line), block=True, timeout=None)
                elif line == '<page>':
                    count += 1
                    inPage = True
                    isRedirect = False
                    inText = False
                    pc = 1
        logging.warning("File Reader Reached End of Control")

class RegexHandler(Process):
    def run(self):
        empty_count = 0
        pattern = re.compile("\[\[File\:(\w|\d|\s|\-|\'|_)*\.\w*\|.|\[\[(\w|\d|\s|\-|\||'|\(|\))*\]\]")
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=basic_auth("neo4j", "neo4J"))
        while empty_count < 10:
            entr = None
            try:
                entr = text_queue.get(block=True, timeout=5)
            except queue.Empty:
                empty_count += 1
                logging.warning("Empty Text Queue Count:" + str(empty_count))
            else:
                empty_count = 0
                search = "MATCH (a:"
                if entr[0] == 0:
                    search = ''.join([search, 'article {id: {id}}), '])
                elif entr[0] == 6:
                    search = ''.join([search, 'file {id: {id}}), '])
                result = re.finditer(pattern, entr[2])
                with driver.session() as session:
                    for k in result:
                        links = k.group(0)[2:-2].split('|')
                        for l in links:
                            success = False
                            err_cnt = 0
                            while not success:
                                try:
                                    l = l.lower()
                                    if l[0:5].lower() == "file:":
                                        session.run(''.join([search, '(b:file {title: {title}}) CREATE \
                                        (a)-[r:file_link {source: a.id, target: b.id}]->(b)']), {"id": entr[1], "title": l})
                                    else:
                                        session.run(''.join([search, '(b:article {title: {title}}) CREATE \
                                        (a)-[r:article_link {source: a.id, target: b.id}]->(b)']), {"id": entr[1], "title": l})
                                except TimeoutError:
                                    #try again!!
                                    err_cnt += 1
                                    logging.warning("Session aquiring time out count: " + str(err_cnt))
                                else:
                                    err_cnt = 0
                                    success = True


file_reader = FileReader(name="FileReader");
regex_1 = RegexHandler(name="Regex 1");
regex_2 = RegexHandler(name="Regex 2");
regex_3 = RegexHandler(name="Regex 3");
# db_transmit_1 = DBTransmitter(name = "DB Transmitter 1");
# db_transmit_2 = DBTransmitter(name = "DB Transmitter 2");
file_reader.start()
regex_1.start()
regex_2.start()
regex_3.start()
# db_transmit_1.start()
# db_transmit_2.start()
file_reader.join()
logging.warning("Joined File Reader!")
regex_1.join()
logging.warning("Joined Regex 1")
regex_2.join()
logging.warning("Joined Regex 2")
regex_3.join()
logging.warning("Joined Regex 3")
