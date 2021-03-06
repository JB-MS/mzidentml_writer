from collections import Iterable, Mapping
from contextlib import contextmanager
from .components import (
    ComponentDispatcher, etree, common_units, element, _element,
    id_maker, default_cv_list, CVParam, UserParam)

try:
    basestring
except:
    basestring = (str, bytes)


def ensure_iterable(obj):
    if not isinstance(obj, Iterable) or isinstance(obj, basestring) or isinstance(obj, Mapping):
        return [obj]
    return obj


_t = tuple()


class XMLWriterMixin(object):

    @contextmanager
    def element(self, element_name, **kwargs):
        try:
            if isinstance(element_name, basestring):
                with element(self.writer, element_name, **kwargs):
                    yield
            else:
                with element_name.element(self.writer, **kwargs):
                    yield
        except AttributeError:
            if self.writer is None:
                raise ValueError(
                    "This writer has not yet been created."
                    " Make sure to use this object as a context manager using the "
                    "`with` notation or by explicitly calling its __enter__ and "
                    "__exit__ methods.")
            else:
                raise

    def write(self, *args, **kwargs):
        try:
            self.writer.write(*args, **kwargs)
        except AttributeError:
            if self.writer is None:
                raise ValueError(
                    "This writer has not yet been created."
                    " Make sure to use this object as a context manager using the "
                    "`with` notation or by explicitly calling its __enter__ and "
                    "__exit__ methods.")
            else:
                raise


class DocumentSection(ComponentDispatcher, XMLWriterMixin):
    def __init__(self, section, writer, parent_context):
        super(DocumentSection, self).__init__(parent_context)
        self.section = section
        self.writer = writer

    def __enter__(self):
        self.toplevel = element(self.writer, self.section)
        self.toplevel.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.toplevel.__exit__(exc_type, exc_value, traceback)
        self.writer.flush()


# ----------------------
# Order of Instantiation
# Providence -> Input -> Protocol -> Identification


class MzIdentMLWriter(ComponentDispatcher, XMLWriterMixin):
    """
    A high level API for generating MzIdentML XML files from simple Python objects.

    This class depends heavily on lxml's incremental file writing API which in turn
    depends heavily on context managers. Almost all logic is handled inside a context
    manager and in the context of a particular document. Since all operations assume
    that they have access to a universal identity map for each element in the document,
    that map is centralized in this instance.

    MzIdentMLWriter inherits from :class:`.ComponentDispatcher`, giving it a :attr:`context`
    attribute and access to all `Component` objects pre-bound to that context with attribute-access
    notation.

    Attributes
    ----------
    outfile : file
        The open, writable file descriptor which XML will be written to.
    xmlfile : lxml.etree.xmlfile
        The incremental XML file wrapper which organizes file writes onto :attr:`outfile`.
        Kept to control context.
    writer : lxml.etree._IncrementalFileWriter
        The incremental XML writer produced by :attr:`xmlfile`. Kept to control context.
    toplevel : lxml.etree._FileWriterElement
        The top level incremental xml writer element which will be closed at the end
        of file generation. Kept to control context
    context : :class:`.DocumentContext`
    """
    def __init__(self, outfile, vocabularies=None, **kwargs):
        super(MzIdentMLWriter, self).__init__(vocabularies)
        self.outfile = outfile
        self.xmlfile = etree.xmlfile(outfile, **kwargs)
        self.writer = None
        self.toplevel = None

    def _begin(self):
        self.writer = self.xmlfile.__enter__()

    def __enter__(self):
        self._begin()
        self.toplevel = element(self.writer, "MzIdentML")
        self.toplevel.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.toplevel.__exit__(exc_type, exc_value, traceback)
        self.writer.flush()
        self.xmlfile.__exit__(exc_type, exc_value, traceback)
        self.outfile.close()

    def close(self):
        self.outfile.close()

    def controlled_vocabularies(self, vocabularies=None):
        if vocabularies is None:
            vocabularies = []
        self.vocabularies.extend(vocabularies)
        cvlist = self.CVList(self.vocabularies)
        cvlist.write(self.writer)

    def providence(self, software=tuple(), owner=None, organization=None):
        """
        Write the analysis providence section, a top-level segment of the MzIdentML document

        This section should be written early on to register the list of software used in this
        analysis

        Parameters
        ----------
        software : dict or list of dict, optional
            A single dictionary or list of dictionaries specifying an :class:`AnalysisSoftware` instance
        owner : dict, optional
            A dictionary specifying a :class:`Person` instance. If missing, a default person will be created
        organization : dict, optional
            A dictionary specifying a :class:`Organization` instance. If missing, a default organization will
            be created
        """
        software = [self.AnalysisSoftware(**(s or {})) for s in ensure_iterable(software)]
        owner = self.Person(**(owner or {}))
        organization = self.Organization(**(organization or {}))

        self.GenericCollection("AnalysisSoftwareList", software).write(self.writer)
        self.Provider(contact=owner.id).write(self.writer)
        self.AuditCollection([owner], [organization]).write(self.writer)

    def inputs(self, source_files=tuple(), search_databases=tuple(), spectra_data=tuple()):
        source_files = [self.SourceFile(**(s or {})) for s in ensure_iterable(source_files)]
        search_databases = [self.SearchDatabase(**(s or {})) for s in ensure_iterable(search_databases)]
        spectra_data = [self.SpectraData(**(s or {})) for s in ensure_iterable(spectra_data)]

        self.Inputs(source_files, search_databases, spectra_data).write(self.writer)

    def sequence_collection(self, db_sequences=tuple(), peptides=tuple(), peptide_evidence=tuple()):
        db_sequences = (self.DBSequence(**(s or {})) for s in ensure_iterable(db_sequences))
        peptides = (self.Peptide(**(s or {})) for s in ensure_iterable(peptides))
        peptide_evidence = (self.PeptideEvidence(**(s or {})) for s in ensure_iterable(peptide_evidence))

        self.SequenceCollection(db_sequences, peptides, peptide_evidence).write(self.writer)

    def spectrum_identification_protocol(self, search_type='ms-ms search', analysis_software_id=1, id=1,
                                         additional_search_params=_t, enzymes=_t, modification_params=_t,
                                         fragment_tolerance=None, parent_tolerance=None, threshold=None):
        enzymes = [self.Enzyme(**(s or {})) for s in ensure_iterable(enzymes)]
        modification_params = [self.SearchModification(**(s or {})) for s in ensure_iterable(modification_params)]
        if isinstance(fragment_tolerance, (list, tuple)):
            fragment_tolerance = self.FragmentTolerance(*fragment_tolerance)
        if isinstance(parent_tolerance, (list, tuple)):
            parent_tolerance = self.ParentTolerance(*parent_tolerance)
        threshold = self.Threshold(threshold)
        protocol = self.SpectrumIdentificationProtocol(
            search_type, analysis_software_id, id, additional_search_params, enzymes, modification_params,
            fragment_tolerance, parent_tolerance, threshold)
        protocol.write(self.writer)

    def spectrum_identification_list(self, id, identification_results=_t):
        converting = (self._spectrum_identification_result(**(s or {})) for s in identification_results)
        self.SpectrumIdentificationList(id=id, identification_results=converting).write(self.writer)

    def _spectrum_identification_result(self, spectrum_id, id, spectra_data_id=1, identifications=_t):
        return self.SpectrumIdentificationResult(
            spectra_data_id=spectra_data_id,
            spectrum_id=spectrum_id,
            id=id,
            identifications=[self._spectrum_identification_item(**(s or {}))
                             for s in ensure_iterable(identifications)])

    def _spectrum_identification_item(self, calculated_mass_to_charge, experimental_mass_to_charge,
                                      charge_state, peptide_id, peptide_evidence_id, score, id, cv_params=_t,
                                      pass_threshold=True, rank=1):
            return self.SpectrumIdentificationItem(
                calculated_mass_to_charge, experimental_mass_to_charge,
                charge_state, peptide_id, peptide_evidence_id, score, id,
                cv_params=ensure_iterable(cv_params), pass_threshold=pass_threshold, rank=rank)
