import multiprocessing
import queue
from multiprocessing import Process, Queue
import time
import logging
import re
import atexit
import argparse
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
                            text_queue.put((ft, ID, line), block=True, timeout=None)
                elif line == '<page>':
                    count += 1
                    logging.warning(count)
                    inPage = True
                    isRedirect = False
                    inText = False
                    pc = 1
        logging.warning("File Reader Reached End of Control")

class RegexHandler(Process):
    def __init__(self, q, name=None):
        self.q = q
        self.driver = GraphDatabase.driver("bolt://localhost:7687", auth=basic_auth("neo4j", "neo4J"))
        super(RegexHandler, self).__init__(name=name)
    def run(self):
        text_queue = self.q
        empty_count = 0
        pattern = re.compile("\[\[File\:(\w|\d|\s|\-|\'|_)*\.\w*\|.|\[\[(\w|\d|\s|\-|\||'|\(|\))*\]\]")
        session = self.driver.session()
        session_count = 0
        while empty_count < 5:
            entr = None
            try:
                entr = text_queue.get(block=True, timeout=1)
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
                            except:
                                #try again!!
                                err_cnt += 1
                                logging.warning("Session aquiring time out count: " + str(err_cnt))
                            else:
                                session_count += 1
                                success = True
                if session_count > 100000:
                    session.close()
                    session = self.driver.session()
                    session_count  = 0
        logging.warning("Finished")

def attempt_delete_relations(relationCount=0):
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=basic_auth("neo4j", "neo4J"))
    if relationCount == 0:
        try:
            session = driver.session()
            res = session.run("match ()-[r]->() delete r")
        except:
            return False
        else:
            return True
    else:
        #Unimplemented
        return False



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Perform multithreaded building of wikipedia database')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--test', action='store_true', default=False)
    parser.add_argument('--test-count', type=int, default=5)
    parser.add_argument('--test-range-start', type=int, default=2)
    parser.add_argument('--queue-size', type=int, default=100000)
    parser.add_argument('--test-cap', type=int, default=1000)

    args = vars(parser.parse_args())
    print(args)
    ITER_COUNT = 1
    N_WORK_LOW = args['threads']
    N_WORK_HIGH = args['threads'] + 1
    if args['test']:
        N_WORK_LOW = args['test_range_start']
        ITER_COUNT = args['test_count']
    TEXT_QUEUE_SIZE = args['queue_size']
    manager = multiprocessing.Manager()
    text_queue = manager.Queue(TEXT_QUEUE_SIZE)
    # db_queue = queue.Queue(DB_QUEUE_SIZE)
    CAP_ENABLED = args['test']
    CAP_COUNT = args['test_cap']


    OUTPUT_FILE = 'timer.txt'
    f = open(OUTPUT_FILE, 'w')
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=basic_auth("neo4j", "neo4J"))

    for NUM_WORKERS in range(N_WORK_LOW, N_WORK_HIGH):
        for i in range(0, ITER_COUNT):
            t = time.time()
            file_reader = FileReader(text_queue, cap_enabled=CAP_ENABLED, cap_count=CAP_COUNT, name="FileReader");

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
            file_reader.join()
            logging.warning("Joined File Reader!")
            for worker in workerArray:
                worker.join()
                logging.warning("Joined " + str(worker))
            f.write(str(time.time() - t))
            f.write('\n')
            f.flush()
            if CAP_ENABLED:
                with driver.session() as session:
                    successful = False
                    while not successful:
                        try:
                            session.run("match ()-[r]->() delete r")
                            logging.warning("Deleted all relationships")
                            session.close()
                        except Exception:
                            pass
                        else:
                            successful = True
    f.close()
