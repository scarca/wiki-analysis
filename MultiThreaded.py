import multiprocessing
from multiprocessing import Process, Queue
import time
import logging
import re
import atexit
from neo4j.v1 import GraphDatabase, basic_auth

logging.basicConfig(level=logging.WARNING, format='(%(processName)s: %(asctime)s) %(message)s',)

class FileReader(Process):
    def __init__(self, q, cap_enabled=False, cap_count=0, name=None):
        self.q = q
        self.cap_enabled = cap_enabled
        self.cap_count = cap_count
        super(FileReader, self).__init__(name=name)
    def run(self):
        text_queue = self.q
        inPage = False
        CAP_ENABLED = self.cap_enabled
        CAP_COUNT = self.cap_count
        with open('enwiki-20170420-pages-articles.xml', 'r') as wiki:
            pc = 0
            ft = 0
            ID = 0
            mc = 0
            count = 1
            inText = False
            isRedirect = None
            for line in wiki:
                line = line.strip()
                if CAP_ENABLED and count >= CAP_COUNT:
                    break
                if count % 100000 == 0 and not inPage:
                    logging.warning(count)
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
                            mc += 1
                            text_queue.put((ft, ID, line), block=True, timeout=None)
                elif line == '<page>':
                    count += 1
                    logging.warning(mc)
                    inPage = True
                    isRedirect = False
                    inText = False
                    pc = 1
        logging.warning("File Reader Reached End of Control")

class RegexHandler(Process):
    def __init__(self, q, name=None):
        self.q = q
        super(RegexHandler, self).__init__(name=name)
    def run(self):
        text_queue = self.q
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
                if len(entr[2]) > 2000000:
                    logging.info("Entry with ID " + str(entr[1]) + "has 2m+ len")
                empty_count = 0
                search = "MATCH (a:"
                if entr[0] == 0:
                    search = ''.join([search, 'article {id: {id}}), '])
                elif entr[0] == 6:
                    search = ''.join([search, 'file {id: {id}}), '])
                result = re.finditer(pattern, entr[2])
                session = driver.session()
                tx = session.begin_transaction()
                for k in result:
                    links = k.group(0)[2:-2].split('|')
                    for l in links:
                        success = False
                        err_cnt = 0
                        while not success:
                            try:
                                l = l.lower()
                                if l[0:5].lower() == "file:":
                                    tx.run(''.join([search, '(b:file {title: {title}}) CREATE \
                                    (a)-[r:file_link {source: a.id, target: b.id}]->(b)']), {"id": entr[1], "title": l})
                                else:
                                    tx.run(''.join([search, '(b:article {title: {title}}) CREATE \
                                    (a)-[r:article_link {source: a.id, target: b.id}]->(b)']), {"id": entr[1], "title": l})
                            except TimeoutError:
                                #try again!!
                                err_cnt += 1
                                logging.warning("Session aquiring time out count: " + str(err_cnt))
                            else:
                                success = True
                tx.commit()
                tx.close()
                session.close()
        logging.warning("Finished")


if __name__ == "__main__":
    TEXT_QUEUE_SIZE = 100000
    manager = multiprocessing.Manager()
    text_queue = manager.Queue(TEXT_QUEUE_SIZE)
    # db_queue = queue.Queue(DB_QUEUE_SIZE)
    CAP_ENABLED = True
    CAP_COUNT = 1000


    file_reader = FileReader(text_queue, cap_enabled=CAP_ENABLED, cap_count=CAP_COUNT, name="FileReader");

    NUM_WORKERS = 12
    workerArray = [''] * NUM_WORKERS;
    for i in range(0, NUM_WORKERS):
        workerArray[i] = RegexHandler(text_queue, name="Regex " + str(i + 1))

    # db_transmit_1 = DBTransmitter(name = "DB Transmitter 1");
    # db_transmit_2 = DBTransmitter(name = "DB Transmitter 2");
    file_reader.start()
    for handler in workerArray:
        handler.start()
    def closer(text_queue):
        for worker in workerArray:
            worker.terminate()
        file_reader.terminate()
        del text_queue
    atexit.register(closer, text_queue)
    # db_transmit_1.start()
    # db_transmit_2.start()
    file_reader.join()
    logging.warning("Joined File Reader!")
    for worker in workerArray:
        worker.join()
