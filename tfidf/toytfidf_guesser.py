import argparse
import json
import logging
import pickle
from collections import defaultdict
from math import log
import os

from typing import Iterable, Tuple, Dict

from tqdm import tqdm
import numpy as np

from sklearn.metrics.pairwise import cosine_similarity

from nltk.tokenize import TreebankWordTokenizer
from nltk import FreqDist

from guesser import Guesser, kTOY_DATA

kUNK = "<UNK>"

def log10(x):
    return log(x) / log(10)

def lower(str):
    return str.lower()


class ToyTfIdfGuesser(Guesser):
    """Class that builds a vocabulary and then computes tf-idf scores
    given a corpus.

    """

    def __init__(self, filename, max_vocab_size=10000,
                 tokenize_function=TreebankWordTokenizer().tokenize,
                 normalize_function=lower, unk_cutoff=2):
        self._vocab_size = -1  # Placeholder until finalized
        self._max_vocab_size = max_vocab_size
        self._total_docs = 0

        self._doc_vectors = None
        self._vocab_final = False
        self._docs_final = False
        
        self._vocab = {}  # word -> id mapping
        self._docs = None
        self._labels = []
        self._unk_cutoff = unk_cutoff

        self._tokenizer = tokenize_function
        self._normalizer = normalize_function

        self.filename = filename

        # Add your code here!
        self._doc_counts = FreqDist()  # For global word frequencies

    def train(self, training_data, answer_field='page', split_by_sentence=False):
        # Extract the data into self.answers, self.questions
        Guesser.train(self, training_data, answer_field, split_by_sentence)

        for question in (progress := tqdm(self.questions)):
            progress.set_description("Creating vocabulary")
            for word in self.tokenize(question):
                self.vocab_seen(word)
        self.finalize_vocab()
               
        for question in (progress := tqdm(self.questions)):
            progress.set_description("Creating document freq")
            self.scan_document(question)
        self.finalize_docs()

        assert self._total_docs == len(self.questions), "Number of documents mismatch"
        self._doc_vectors = np.zeros((len(self.questions), self._vocab_size))
        for row_id, question in enumerate(progress := tqdm(self.questions)):
            progress.set_description("Creating document vecs")            
            self._doc_vectors[row_id] = self.embed(question)

    def __call__(self, question, max_n_guesses=1):
        """
        Given a question, find the closest document in the training set and
        return a dictionary with that guess.
        
        Before you start coding this, remember what this function did in the
        last homework: given a query, it needs to find the training item
        closest to the query.  To do that, you need to do three things: turn
        the query into a vector, compute the similarity of that vector with
        each row in the matrix, and return the metadata associated with that
        row.

        We've helped you out by structuring the code so that it should be easy
        for you to complete it.  \`question\_tfidf\` is the vector after you
        embed it.  This code is already done for you (assuming you've
        completed \`inv\_docfreq\` already).

        Then you'll need to go through the rows in \`self.\_doc\_vectors\` and
        find the closest row.  Call whatever the closest is \`best\` and
        return the appropriate metadata.  This is implemented for you already.

        """
        
        assert max_n_guesses == 1, "We only support top guess"
        
        question_tfidf = self.embed(question).reshape(1, -1)
        similarities = cosine_similarity(question_tfidf, self._doc_vectors)[0]
        best = similarities.argmax()
        print(f"[__call__] Best match index: {best}, Similarity: {similarities[best]}. (Expected: Highest similarity index and value)")
        return [{"question": self.questions[best], "guess": self.answers[best], "confidence": similarities[best]}]

    def save(self):
        path = self.filename
        logging.debug("Writing information to %s" % path)
        Guesser.save_questions_and_answers(self)
        with open("%s.vocab.pkl" % path, 'wb') as f:
            pickle.dump(self._vocab, f)
        
        with open("%s.tfidf.pkl" % path, 'wb') as f:
            pickle.dump(self._doc_vectors, f)

        with open("%s.doccounts.pkl" % path, 'wb') as f:
            pickle.dump(self._doc_counts, f)


    def load(self):
        Guesser.load_questions_and_answers(self)
        path = self.filename
        with open("%s.vocab.pkl" % path, 'rb') as f:
            self._vocab = pickle.load(f)
        self._vocab_size = len(self._vocab)
        self._vocab_final = True

        with open("%s.tfidf.pkl" % path, 'rb') as f:
            self._doc_vectors = pickle.load(f)
        with open("%s.doccounts.pkl" % path, 'rb') as f:
            self._doc_counts = pickle.load(f)

        self._total_docs = self._doc_vectors.shape[0]
        self._docs_final = True

        assert self._vocab_size == self._doc_vectors.shape[1]
        logging.debug("Loaded %i docs with vocab size %i from %s" %
                          (self._total_docs, self._vocab_size, path))

        
        
    def vocab_seen(self, word: str, count: int=1):
        """Tells the language model that a word has been seen @count times.  This
        will be used to build the final vocabulary.

        word -- The string represenation of the word.  After we
        finalize the vocabulary, we'll be able to create more
        efficient integer representations, but we can't do that just
        yet.

        count -- How many times we've seen this word (by default, this is one).
        """

        assert not self._vocab_final, \
            "Trying to add new words to finalized vocab"
        print(f"[vocab_seen] Before: Word '{word}' has {self._doc_counts[word]} occurrences.")
        
        self._doc_counts[word] += count  # Track global word frequency

        print(f"[vocab_seen] After: Word '{word}' should now have {self._doc_counts[word]} occurrences. (Expected: Previous + {count})")
        
    def scan_document(self, text: str):
        """
        Tokenize a piece of text and compute the document frequencies.

        text -- The raw string containing a document
        """

        assert self._vocab_final, "scan_document can only be run with finalized vocab"
        assert not self._docs_final, "scan_document can only be run with non-finalized doc counts"
        
        print(f"[scan_document] Scanning document. Current doc count: {self._total_docs}.")
        for word in self._tokenizer(text):
            # Map to <UNK> if infrequent
            word = word if word in self._vocab else kUNK
            self._doc_counts[word] += 1  

        self._total_docs += 1
        print(f"[scan_document] New total doc count: {self._total_docs}. Expected: Previous count + 1.")
        
    def embed(self, text):
        # You don't need to modify this code
        vector = np.zeros(self._vocab_size)
        doc_frequency = FreqDist(x for x in self._tokenizer(text) if x in self._vocab)

        for word in doc_frequency:
            index = self.vocab_lookup(word)
            vector[index] = doc_frequency.freq(word) * self.inv_docfreq(index)
        return vector
        
    def tokenize(self, sent: str) -> Iterable[int]:
        """Return a generator over tokens in the sentence; return the vocab
        of a sentence if finalized, otherwise just return the raw string.

        sent -- A string of English text

        """
        
        # You don't need to modify this code.
        for ii in self._tokenizer(sent):
            word = self._normalizer(ii)
            if self._vocab_final:
                yield self.vocab_lookup(word)
            else:
                yield word

    def doc_tfidf(self, doc: str) -> Dict[Tuple[str, int], float]:
        """Given a document, create a dictionary representation of its tfidf vector

        doc -- raw string of the document"""

        assert self._docs_final, "Documents must be finalized"
        
        counts = FreqDist(self.tokenize(doc))
        d = {}
        for ii in self._tokenizer(doc):
            ww = self.vocab_lookup(ii)
            d[(ww, ii)] = counts.freq(ww) * self.inv_docfreq(ww)
        return d
                
    def global_freq(self, word: int) -> float:
        """Return the frequency of a word over the trainin set if it's
        in the vocabulary, zero otherwise.

        This should be summed over all documents.

        word -- The integer lookup of the word.
        """

        word_str = self.vocab_key(word)
        freq = self._doc_counts[word_str] / sum(self._doc_counts.values())
        print(f"[global_freq] Frequency of '{word_str}': {freq}. (Expected: Calculated based on total occurrences)")
        return freq

    def inv_docfreq(self, word: int) -> float:
        """Compute the inverse document frequency of a word.  Return 0.0 if
        the word index is outside of our vocabulary (however, this should 
        never happen in normal operation).

        Keyword arguments:
        word -- The word to look up the document frequency of a word.

        """
        assert self._docs_final, "Documents must be finalized"
        
        doc_freq = self._doc_freq.get(word, 0)
        inv_df = log10(self._total_docs / (1 + doc_freq)) if doc_freq else 0
        print(f"[inv_docfreq] IDF of word ID {word} ('{self.vocab_key(word)}'): {inv_df}. (Expected: Based on formula)")
        return inv_df

    def vocab_key(self, word_id):
        """Helper to get the word string given the vocab ID"""
        for word, id in self._vocab.items():
            if id == word_id:
                return word
        return kUNK

    def vocab_lookup(self, word: str) -> int:
        """
        Given a word, provides a vocabulary integer representation.  Words under the
        cutoff threshold shold have the same value.  All words with counts
        greater than or equal to the cutoff should be unique and consistent.

        This is useful for turning words into features in later homeworks.

        word -- The word to lookup
        """
        assert self._vocab_final, \
            "Vocab must be finalized before looking up words"

        lookup = -1
        if word in self._vocab:
            lookup = self._vocab[word]
        else:
            lookup = self._vocab[kUNK]

        assert lookup >= 0 and lookup < self._vocab_size, "Vocabulary out of bounds.  Did you forget to update self._vocab_size?"
        return lookup

    def finalize_vocab(self):
        """
        Fixes the vocabulary as static, prevents keeping additional vocab from
        being added
        """
        print(f"[finalize_vocab] Total unique words before pruning: {len(self._doc_counts)}. Expected: Depends on dataset.")
        # Construct vocabulary keeping words above _unk_cutoff
        sorted_counts = sorted(self._doc_counts.items(), key=lambda x: x[1], reverse=True)
        self._vocab = {word: i for i, (word, count) in enumerate(sorted_counts[:self._max_vocab_size])
                       if count >= self._unk_cutoff}

        self._vocab[kUNK] = len(self._vocab)  # Add <UNK> token at the end
        self._vocab_size = len(self._vocab)

        logging.debug("%i vocab elements, including: %s" % (self._vocab_size, str(self._vocab.keys())[:60]))
        assert self._vocab_size < self._max_vocab_size, "Vocab size too large %i > %i" % (self._vocab_size, self._max_vocab_size)

        self._vocab_final = True
        
        print(f"[finalize_vocab] Vocab size after pruning: {len(self._vocab)}. Expected: <= Max vocab size, considering UNK.")

    def finalize_docs(self):
        # You don't need to do anything here        
        self._docs_final = True

        logging.debug("Document counts final after %i docs, some example inverse document frequencies:" % self._total_docs)
        for ww in list(self._vocab.keys())[:10]:
            vocab_lookup = self._vocab[ww]
            logging.debug("%10s (%3i): %0.2f %i" % (ww, vocab_lookup, self.inv_docfreq(vocab_lookup), self.global_freq(vocab_lookup)))
        

if __name__ == "__main__":
    # Load a tf-idf guesser and run it on some questions
    from params import *
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    add_general_params(parser)
    add_guesser_params(parser)
    add_question_params(parser)

    flags = parser.parse_args()
    
    guesser = load_guesser(flags)
    guesser.train(kTOY_DATA["train"], answer_field='page', split_by_sentence=False)

    logging.debug("Document matrix is %i by %i, has %i non-zero entries" %
                      (guesser._doc_vectors.shape[0],
                       guesser._doc_vectors.shape[1],
                       np.count_nonzero(guesser._doc_vectors)))

    for query_row in kTOY_DATA["dev"]:
        query = query_row["text"]
        print("----------------------")
        guess = guesser(query)
        print(query, guess)
